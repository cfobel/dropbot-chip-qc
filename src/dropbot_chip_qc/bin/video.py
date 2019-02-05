# -*- encoding: utf-8 -*-
import logging

from ..video import main


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')
    main()
