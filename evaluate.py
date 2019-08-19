"""
This code is modified from batra-mlp-lab's repository.
https://github.com/batra-mlp-lab/visdial-challenge-starter-pytorch
"""
import argparse
import datetime
import gc
import json
import math
import os
from tqdm import tqdm
import numpy as np

import torch
import torch.nn as nn
from torch.autograd import Variable
from torch.utils.data import DataLoader

from dataloader import VisDialDataset
from encoders import Encoder
from decoders import Decoder
from utils import process_ranks, scores_to_ranks, get_gt_ranks
from utils import utils

parser = argparse.ArgumentParser()
VisDialDataset.add_cmdline_args(parser)

parser.add_argument_group('Evaluation related arguments')
parser.add_argument('-load_path', default='checkpoints/model.pth',
                        help='Checkpoint to load path from')
parser.add_argument('-split', default='val', choices=['val', 'test'],
                        help='Split to evaluate on')
parser.add_argument('-use_gt', default=True,
                        help='Whether to use ground truth for retrieving ranks')
parser.add_argument('-batch_size', default=80, type=int, help='Batch size')
parser.add_argument('-gpuid', default=0, type=int, help='GPU id to use')
parser.add_argument('-overfit', default=False,
                        help='Use a batch of only 5 examples, useful for debugging')

parser.add_argument_group('Submission related arguments')
parser.add_argument('-save_ranks', default=False,
                        help='Whether to save retrieved ranks')
parser.add_argument('-save_path', default='checkpoints/results.json',
                        help='Path of json file to save ranks')

# ----------------------------------------------------------------------------
# input arguments and options
# ----------------------------------------------------------------------------
args = parser.parse_args()
if args.use_gt:
    if args.split == 'test':
        print("Warning: No ground truth for test split, changing use_gt to False.")
        args.use_gt = False
    elif args.split == 'val' and args.save_ranks:
        print("Warning: Cannot generate submission json if use_gt is True.")
        args.save_ranks = False

np.random.seed(5912)
torch.cuda.manual_seed_all(5912)

# ----------------------------------------------------------------------------
# read saved model and args
# ----------------------------------------------------------------------------
components = torch.load(args.load_path)
model_args = components['model_args']
model_args.gpuid = args.gpuid
model_args.batch_size = args.batch_size

# set this because only late fusion encoder is supported yet
args.concat_history = False

for arg in vars(args):
    print('{:<20}: {}'.format(arg, getattr(args, arg)))

# ----------------------------------------------------------------------------
# loading dataset wrapping with a dataloader
# ----------------------------------------------------------------------------
dataset = VisDialDataset(args, [args.split])
dataloader = DataLoader(dataset,
                        batch_size=args.batch_size,
                        shuffle=False,
                        collate_fn=dataset.collate_fn)

# iterations per epoch
setattr(args, 'iter_per_epoch',
    math.floor(dataset.num_data_points[args.split] / args.batch_size))
print("{} iter per epoch.".format(args.iter_per_epoch))

# ----------------------------------------------------------------------------
# setup the model

encoder = Encoder(model_args)
decoder = Decoder(model_args, encoder)

encoder = nn.DataParallel(encoder).cuda()
decoder = nn.DataParallel(decoder).cuda()

encoder.load_state_dict(components.get('encoder', components))
decoder.load_state_dict(components.get('decoder', components))
print("Loaded model from {}".format(args.load_path))

if args.gpuid >= 0:
    encoder = encoder.cuda()
    decoder = decoder.cuda()

# ----------------------------------------------------------------------------
# evaluation
# ----------------------------------------------------------------------------
print("Evaluation start time: {}".format(
    datetime.datetime.strftime(datetime.datetime.utcnow(), '%d-%b-%Y-%H:%M:%S')))
encoder.eval()
decoder.eval()

if args.use_gt:
    # ------------------------------------------------------------------------
    # calculate automatic metrics and finish
    # ------------------------------------------------------------------------
    all_ranks = []
    for i, batch in enumerate(tqdm(dataloader)):
        for key in batch:
            if not isinstance(batch[key], list):
                batch[key] = Variable(batch[key], volatile=True)
                if args.gpuid >= 0:
                    batch[key] = batch[key].cuda()

        enc_out = encoder(batch)
        dec_out = decoder(enc_out, batch)
        ranks = scores_to_ranks(dec_out.data)
        gt_ranks = get_gt_ranks(ranks, batch['ans_ind'].data)
        all_ranks.append(gt_ranks)
    all_ranks = torch.cat(all_ranks, 0)
    process_ranks(all_ranks)
    gc.collect()
else:
    # ------------------------------------------------------------------------
    # prepare json for submission
    # ------------------------------------------------------------------------
    ranks_json = []
    for i, batch in enumerate(tqdm(dataloader)):
        for key in batch:
            if not isinstance(batch[key], list):
                batch[key] = Variable(batch[key], volatile=True)
                if args.gpuid >= 0:
                    batch[key] = batch[key].cuda()

        enc_out = encoder(batch)
        dec_out = decoder(enc_out, batch)
        ranks = scores_to_ranks(dec_out.data)
        ranks = ranks.view(-1, 10, 100)

        for i in range(len(batch['img_fnames'])):
            # cast into types explicitly to ensure no errors in schema
            if args.split == 'test':
                ranks_json.append({
                    'image_id': int(batch['img_fnames'][i]),
                    'round_id': int(batch['num_rounds'][i]),
                    'ranks': list(ranks[i][batch['num_rounds'][i] - 1])
                })
            else:
                for j in range(batch['num_rounds'][i]):
                    ranks_json.append({
                        'image_id': int(batch['img_fnames'][i]),
                        'round_id': int(j + 1),
                        'ranks': list(ranks[i][j])
                    })
        gc.collect()

if args.save_ranks:
    print("Writing ranks to {}".format(args.save_path))
    os.makedirs(os.path.dirname(args.save_path), exist_ok=True)
    json.dump(ranks_json, open(args.save_path, 'w'))
