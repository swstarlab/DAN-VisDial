"""
This code is modified from Jinhwa Kim's repository.
https://github.com/jnhwkim/ban-vqa

Reads in a tsv file with pre-trained bottom up attention features 
of the adaptive number of boxes and stores it in HDF5 format.  
Also store {image_id: feature_idx} as a pickle file.

Hierarchy of HDF5 file:
{ 'image_features': num_boxes x 2048
  'image_bb': num_boxes x 4
  'spatial_features': num_boxes x 6
  'pos_boxes': num_images x 2 }

"""

from __future__ import print_function

import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import base64
import csv
import h5py
import pickle as cPickle
import numpy as np
from utils import utils

csv.field_size_limit(sys.maxsize)

def extract(split, infiles):
    FIELDNAMES = ['image_id', 'image_w', 'image_h', 'num_boxes', 'boxes', 'features']
    # feature data name to write
    data_file = {
        'train': '/data/data/visdial/train_feature/train_0.9_btmup_f.hdf5', 
        'val': '/data/data/visdial/val_feature/val_0.9_btmup_f.hdf5',
        'test': '/data/data/visdial/test_feature/test_btmup_f.hdf5'}
    indices_file = {
        'train': '/data/data/visdial/train_feature/train_0.9_imgid2idx.pkl',
        'val': '/data/data/visdial/val_feature/val_0.9_imgid2idx.pkl',
        'test': '/data/data/visdial/test_feature/test_imgid2idx.pkl'}
    ids_file = {
        'train': '/data/data/visdial/train_feature/train_0.9_ids.pkl',
        'val': '/data/data/visdial/val_feature/val_0.9_ids.pkl',
        'test': '/data/data/visdial/test_feature/test_ids.pkl'
    }
    path_imgs = {
        'train': '/data/data/visdial/images/train2014',
        'val': '/data/data/visdial/images/val2014',
        'test': '/data/data/visdial/images/VisualDialog_test2018'
    }
    known_num_boxes = {
        'train': None,
        'val': None,
        'test': None,
    }
    feature_length = 2048
    min_fixed_boxes = 10
    max_fixed_boxes = 100

    if os.path.exists(ids_file[split]):
        imgids = cPickle.load(open(ids_file[split], 'rb'))
    else:
        imgids = utils.load_imageid(path_imgs[split])
        cPickle.dump(imgids, open(ids_file[split], 'wb'))

    h = h5py.File(data_file[split], 'w')

    if known_num_boxes[split] is None:
        num_boxes = 0
        for infile in infiles:
            print("reading tsv...%s" % infile)
            with open(infile, "r+") as tsv_in_file:
                reader = csv.DictReader(tsv_in_file, delimiter='\t', fieldnames=FIELDNAMES)
                for item in reader:
                    item['num_boxes'] = int(item['num_boxes'])
                    image_id = int(item['image_id'])
                    if image_id in imgids:
                        num_boxes += item['num_boxes']
    else:
        num_boxes = known_num_boxes[split]

    print('num_boxes=%d' % num_boxes)

    img_features = h.create_dataset(
        'image_features', (num_boxes, feature_length), 'f')
    img_bb = h.create_dataset(
        'image_bb', (num_boxes, 4), 'f')
    spatial_img_features = h.create_dataset(
        'spatial_features', (num_boxes, 6), 'f')
    pos_boxes = h.create_dataset(
        'pos_boxes', (len(imgids), 2), dtype='int32')

    counter = 0
    num_boxes = 0
    indices = {}

    for infile in infiles:
        unknown_ids = []
        print("reading tsv...%s" % infile)
        with open(infile, "r+") as tsv_in_file:
            reader = csv.DictReader(tsv_in_file, delimiter='\t', fieldnames=FIELDNAMES)
            for item in reader:
                item['num_boxes'] = int(item['num_boxes'])
                item['boxes'] = bytes(item['boxes']).encode('utf')
                item['features'] = bytes(item['features']).encode('utf')
                image_id = int(item['image_id'])
                image_w = float(item['image_w'])
                image_h = float(item['image_h'])
                bboxes = np.frombuffer(
                    base64.decodestring(item['boxes']),
                    dtype=np.float32).reshape((item['num_boxes'], -1))

                box_width = bboxes[:, 2] - bboxes[:, 0]
                box_height = bboxes[:, 3] - bboxes[:, 1]
                scaled_width = box_width / image_w
                scaled_height = box_height / image_h
                scaled_x = bboxes[:, 0] / image_w
                scaled_y = bboxes[:, 1] / image_h

                box_width = box_width[..., np.newaxis]
                box_height = box_height[..., np.newaxis]
                scaled_width = scaled_width[..., np.newaxis]
                scaled_height = scaled_height[..., np.newaxis]
                scaled_x = scaled_x[..., np.newaxis]
                scaled_y = scaled_y[..., np.newaxis]

                spatial_features = np.concatenate(
                    (scaled_x,
                     scaled_y,
                     scaled_x + scaled_width,
                     scaled_y + scaled_height,
                     scaled_width,
                     scaled_height),
                    axis=1)

                if image_id in imgids:
                    imgids.remove(image_id)
                    indices[image_id] = counter
                    pos_boxes[counter,:] = np.array([num_boxes, num_boxes + item['num_boxes']])
                    img_bb[num_boxes:num_boxes+item['num_boxes'], :] = bboxes
                    img_features[num_boxes:num_boxes+item['num_boxes'], :] = np.frombuffer(
                        base64.decodestring(item['features']),
                        dtype=np.float32).reshape((item['num_boxes'], -1))
                    spatial_img_features[num_boxes:num_boxes+item['num_boxes'], :] = spatial_features
                    counter += 1
                    num_boxes += item['num_boxes']
                else:
                    unknown_ids.append(image_id)

        print('%d unknown_ids...' % len(unknown_ids))
        print('%d image_ids left...' % len(imgids))

    if len(imgids) != 0:
        print('Warning: %s_image_ids is not empty' % split)

    cPickle.dump(indices, open(indices_file[split], 'wb'))
    h.close()
    print("done!")

if __name__ == '__main__':
    infile = ['/data/data/visdial/train_feature/visdial_train.tsv.1', 
              '/data/data/visdial/train_feature/visdial_train_t.tsv.1']
    extract('train', infile) 

    infile = ['/data/data/visdial/test_feature/visdial_1.0_test_btup.tsv']
    extract('test', infile)
