# -*- encoding: utf-8 -*-
import argparse
import logging
import sys

from ..video import main

VIDEO_PARSER = argparse.ArgumentParser(add_help=False)
VIDEO_PARSER.add_argument('-V', '--video-device', help='Video device ID '
                          '(default=%(default)s).', type=int, default=0)
VIDEO_PARSER.add_argument('-r', '--resolution', help='Video capture resolution'
                          ' (default=%(default)s).', nargs='?',
                          choices=['1920x1080', '1280x720', '640x480'],
                          default='1280x720')


def parse_args(args=None):
    if args is None:
        args = sys.argv[1:]

    parser = argparse.ArgumentParser(description='DropBot chip video viewer',
                                     parents=[VIDEO_PARSER])

    args = parser.parse_args(args)
    args.resolution = tuple(map(int, args.resolution.split('x')))
    return args


if __name__ == '__main__':
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG,
                        format="[%(asctime)s] %(levelname)s: %(message)s")

    main(resolution=args.resolution, device_id=args.video_device)
