# -*- coding: utf-8 -*-
'''
.. versionadded:: v0.12.0
'''
import functools as ft

from logging_helpers import _L
import dmf_chip as dc
import ipywidgets as ipw
import numpy as np
import pandas as pd
import path_helpers as ph
import si_prefix as si

from .mqtt_proxy import DropBotMqttProxy
from .render import get_summary_dict, render_summary


# For colors, see: https://gist.github.com/cfobel/fd939073cf13a309d7a9
light_blue = '#88bde6'
light_green = '#90cd97'


def executor_control(controller, output_directory):
    ui = controller.ui
    channel_electrodes = ui['channel_electrodes']
    channel_patches = ui['channel_patches']
    chip_info = ui['chip_info']
    chip_info_mm = ui['chip_info_mm']
    dropbot_settings = ui['dropbot_settings']
    figure = ui['figure']
    signals = ui['signals']

    def calibrate(*args):
        sheet_capacitance, voltage = \
            controller.calibrate_sheet_capacitance(30e-6)

    def pause(*args):
        controller.pause()

    def reset(*args):
        bad_channels.value = []
        button_start.description = 'Start test'
        controller.reset()

    def save_results(*args):
        chip_uuid = dropbot_settings.fields['Chip UUID:'].text()
        controller.save_results(output_directory, chip_uuid)

    def start(*args):
        button_start.disabled = True
        button_start.description = 'Resume test'
        button_pause.disabled = False
        controller.start(bad_channels.value)

    def setattr_(obj, attr, value, *args, **kwargs):
        _L().info('%s, %s, %s', obj, attr, value)
        return setattr(obj, attr, value)

    button_start = ipw.Button(description='Start test')
    button_start.on_click(start)


    button_pause = ipw.Button(description='Pause test', disabled=True)
    button_pause.on_click(pause)

    button_reset = ipw.Button(description='Reset')
    button_reset.on_click(reset)
    button_save = ipw.Button(description='Save test report')
    button_save.on_click(save_results)

    buttons = ipw.HBox([button_start, button_pause, button_reset, button_save])
    bad_channels = ipw.SelectMultiple(description='Bad channels',
                                      options=sorted(channel_patches.index),
                                      layout=ipw.Layout(width='50%',
                                                        height='200px'))

    button_sheet_capacitance = ipw.Button(description='Calibrate')
    button_sheet_capacitance.on_click(calibrate)

    accordion = ipw.Accordion([buttons, bad_channels,
                               button_sheet_capacitance])
    accordion.set_title(0, 'Executor actions')
    accordion.set_title(1, 'Bad channels')
    accordion.set_title(2, 'Sheet capacitance')

    accordion.start_on_complete = ft.partial(setattr_, button_start, 'disabled', False)
    accordion.pause_on_complete = ft.partial(setattr_, button_pause, 'disabled', True)
    signals.signal('test-complete').connect(accordion.start_on_complete)
    signals.signal('test-interrupt').connect(accordion.start_on_complete)
    signals.signal('test-complete').connect(accordion.pause_on_complete)
    signals.signal('test-interrupt').connect(accordion.pause_on_complete)

    return accordion
