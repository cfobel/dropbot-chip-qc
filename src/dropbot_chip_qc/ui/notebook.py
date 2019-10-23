# -*- coding: utf-8 -*-
import functools as ft

from logging_helpers import _L
import dmf_chip as dc
import ipywidgets as ipw
import numpy as np
import pandas as pd
import path_helpers as ph
import si_prefix as si

from .mdi import DropBotMqttProxy
from .render import get_summary_dict, render_summary


# For colors, see: https://gist.github.com/cfobel/fd939073cf13a309d7a9
light_blue = '#88bde6'
light_green = '#90cd97'


def executor_control(aproxy, ui, executor, output_directory):
    channel_electrodes = ui['channel_electrodes']
    channel_patches = ui['channel_patches']
    chip_info = ui['chip_info']
    chip_info_mm = ui['chip_info_mm']
    dropbot_settings = ui['dropbot_settings']
    figure = ui['figure']
    signals = ui['signals']

    def calibrate_sheet_capacitance(*args):
        '''Calibrate sheet capacitance with liquid present

        **NOTE** Prior to running the following cell:

         - _at least_ one electrode **MUST** be **actuated**
         - all actuated electrodes **MUST** be completely covered with liquid

        It may be helpful to use the interactive figure UI to manipulate liquid until
        the above criteria are met.

        This function performs the following steps:

         1. Measure **total capacitance** across **all actuated electrodes**
         2. Compute sheet capacitance with liquid present ($\Omega_L$) based on nominal
            areas of actuated electrodes from `chip_file`
         3. Compute voltage to match 25 μN of force, where
            $F = 10^3 \cdot 0.5 \cdot \Omega_L \cdot V^2$
         4. Set DropBot voltage to match target of 25 μN force.
        '''
        proxy = DropBotMqttProxy.from_uri('dropbot', aproxy.__client__._host)
        name = 'liquid'
        states = proxy.state_of_channels
        channels = states[states > 0].index.tolist()
        electrodes_by_id = pd.Series(chip_info_mm['electrodes'],
                                     index=(e['id'] for e in
                                            chip_info_mm['electrodes']))
        actuated_area = (electrodes_by_id[channel_electrodes[channels]]
                         .map(lambda x: x['area'])).sum()
        capacitance = pd.Series(proxy.capacitance(0)
                                for i in range(20)).median()
        sheet_capacitance = capacitance / actuated_area
        message = ('Measured %s sheet capacitance: %sF/%.1f mm^2 = %sF/mm^2'
                   % (name, si.si_format(capacitance), actuated_area,
                      si.si_format(sheet_capacitance)))
        print(message)
        target_force = 30e-6  # i.e., 30 μN
        voltage = np.sqrt(target_force / (1e3 * 0.5 * sheet_capacitance))
        # Set voltage in DropBot settings UI
        dropbot_settings.fields['Voltage:'].setValue(voltage)

    def pause(*args):
        executor.pause()

    def reset(*args):
        executor.reset()
        button_start.description = 'Start test'
        bad_channels.value = []
        channel_patches.map(lambda x: x.set_facecolor(light_blue))
        for collection in list(figure._ax.collections):
            collection.remove()
        figure._ax.figure.canvas.draw()

    def save_results(*args):
        output_dir = ph.path(output_directory)
        chip_uuid = dropbot_settings.fields['Chip UUID:'].text()
        channel_plan, completed_transfers = executor.channel_plan()
        proxy = DropBotMqttProxy.from_uri('dropbot', aproxy.__client__._host)
        summary_dict = \
            get_summary_dict(proxy, chip_info,
                             sorted(set(executor.base_channel_plan)),
                             channel_plan, completed_transfers,
                             chip_uuid=chip_uuid)
        output_path = output_dir.joinpath('Chip test report - %s.html' %
                                          summary_dict['chip_uuid'])
        print('save to: `%s`' % output_path)
        render_summary(output_path, **summary_dict)

    def start(*args):
        executor.channels_graph = executor.base_channels_graph.copy()
        executor.remove_channels(bad_channels.value)
        executor.start(aproxy, signals)
        button_start.disabled = True
        button_start.description = 'Resume test'
        button_pause.disabled = False

    def setattr_(obj, attr, value, *args, **kwargs):
        _L().info('%s, %s, %s', obj, attr, value)
        return setattr(obj, attr, value)

    button_start = ipw.Button(description='Start test')
    button_start.on_click(start)
    # button_start.on_test_complete = ft.partial(setattr_, button_start,
                                               # 'disabled', False)


    button_pause = ipw.Button(description='Pause test', disabled=True)
    button_pause.on_click(pause)
    # button_pause.on_test_complete = ft.partial(setattr_, button_pause,
                                               # 'disabled', True)

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
    button_sheet_capacitance.on_click(calibrate_sheet_capacitance)

    reset()
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
