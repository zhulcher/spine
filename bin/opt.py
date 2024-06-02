#!/usr/bin/env python
from spine.model.experimental.hyperopt.search import search
from spine.main import process_config
import os
import sys
import yaml
from os import environ
import argparse

current_directory = os.path.dirname(os.path.abspath(__file__))
current_directory = os.path.dirname(current_directory)
sys.path.insert(0, current_directory)


def main(config):
    cfg_file = config
    if not os.path.isfile(cfg_file):
        cfg_file = os.path.join(current_directory, 'config', config)
    if not os.path.isfile(cfg_file):
        print(config, 'not found...')
        sys.exit(1)

    cfg = yaml.load(open(cfg_file, 'r'), Loader=yaml.Loader)

    if environ.get('CUDA_VISIBLE_DEVICES') is not None and cfg['hyperparameter_search']['gpus'] == '-1':
        cfg['hyperparameter_search']['gpus'] = os.getenv('CUDA_VISIBLE_DEVICES')

    process_config(cfg)

    search(cfg)


if __name__ == '__main__':
    import torch
    parser = argparse.ArgumentParser()
    parser.add_argument('config')
    parser.add_argument("--detect_anomaly",
                        help="Turns on autograd.detect_anomaly for debugging",
                        action='store_true')
    args = parser.parse_args()
    if args.detect_anomaly:
        with torch.autograd.detect_anomaly():
            main(args.config)
    else:
        main(args.config)
