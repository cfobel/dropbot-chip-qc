import functools as ft

from logging_helpers import _L
import ipywidgets as ipw
import path_helpers as ph

from .mdi import DropBotMqttProxy
from .render import get_summary_dict, render_summary


# For colors, see: https://gist.github.com/cfobel/fd939073cf13a309d7a9
light_blue = '#88bde6'
light_green = '#90cd97'


def executor_control(chip_info, aproxy, signals, figure, channel_patches,
                     executor, output_directory, get_uuid=None):
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
        chip_uuid = '<unknown>' if get_uuid is None else get_uuid()
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

    reset()
    accordion = ipw.Accordion([buttons, bad_channels])
    accordion.set_title(0, 'Executor actions')
    accordion.set_title(1, 'Bad channels')

    accordion.start_on_complete = ft.partial(setattr_, button_start, 'disabled', False)
    accordion.pause_on_complete = ft.partial(setattr_, button_pause, 'disabled', True)
    signals.signal('test-complete').connect(accordion.start_on_complete)
    signals.signal('test-interrupt').connect(accordion.start_on_complete)
    signals.signal('test-complete').connect(accordion.pause_on_complete)
    signals.signal('test-interrupt').connect(accordion.pause_on_complete)
    return accordion
