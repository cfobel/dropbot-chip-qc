# -*- coding: utf-8 -*-
'''
.. versionadded:: X.X.X
'''
import copy
import pkgutil
import re
import subprocess as sp
import tempfile

import dmf_chip as dc
import dropbot as db
import dropbot.chip
import dropbot.proxy
import dropbot.self_test
import jinja2
import json_tricks
import matplotlib as mpl
import matplotlib.pyplot as plt
import pandas as pd
import path_helpers as ph
import qrcode

from .. import __version__

# For colors, see: https://gist.github.com/cfobel/fd939073cf13a309d7a9
dark_green = '#059748'
light_green = '#90cd97'
light_blue = '#88bde6'
light_orange = '#fbb258'
dark_orange = '#df5c24'
dark_red = '#cb2027'


def draw_route(axis, from_, to_, **kwargs):
    # Draw route over electrodes as sequence of arrows.
    # See: https://stackoverflow.com/a/7543518/345236
    q = axis.quiver(from_.x, from_.y,
                    to_.x.values - from_.x,
                    to_.y.values - from_.y,
                    scale=1,
                    scale_units='xy', angles='xy',
                    **kwargs)
    # Ensure route is drawn on top layer of plot.
    q.set_zorder(20)
    return q


def render_plan(axis, df_channel_centers, channel_patches, channel_plan,
                completed_transfers):
    from_ = df_channel_centers.loc[channel_plan[:-1]]
    to_ = df_channel_centers.loc[channel_plan[1:]]

    q1 = draw_route(axis, from_, to_, color=dark_orange)

    if completed_transfers:
        completed_plan = ([completed_transfers[0]['channels'][0]] +
                          [t['channels'][1] for t in completed_transfers])
    else:
        completed_plan  = []

    from_ = df_channel_centers.loc[completed_plan[:-1]]
    to_ = df_channel_centers.loc[completed_plan[1:]]

    q2 = draw_route(axis, from_, to_, color=dark_green)

    for i, patch_i in channel_patches.loc[channel_plan[1:]].items():
        patch_i.set_color(light_orange)

    for i, patch_i in channel_patches.loc[completed_plan].items():
        patch_i.set_color(light_green)

    return q1, q2


def draw_results(chip_info, channel_plan, completed_transfers,
                 test_channels=None, axes=None):
    if axes is None:
        fig, axes = plt.subplots(1, 2, figsize=(20, 20))

    chip_info_mm = dc.to_unit(chip_info, 'mm')

    electrode_channels = pd.Series({e['id']: e['channels'][0]
                                    for e in chip_info['electrodes']})

    for i, ax in enumerate(axes):
        result = dc.draw(chip_info, ax=ax, unit='mm', labels=(i == 0))
        for id_i, p in result['patches'].items():
            p.set_edgecolor('none')
            p.set_facecolor(light_blue)
        labels = {t.get_text(): t for t in result['axis'].texts}
        for id_i, label_i in labels.items():
            label_i.set_text(electrode_channels[id_i])

    x_coords = [p[0] for e in chip_info_mm['electrodes'] for p in e['points']]
    y_coords = [p[1] for e in chip_info_mm['electrodes'] for p in e['points']]

    for ax in axes:
        ax.set_xlim(min(x_coords), max(x_coords))
        ax.set_ylim(max(y_coords), min(y_coords))
        ax.set_axis_off()
        ax.set_frame_on(False)

    patches = result['patches']
    channel_patches = pd.Series(patches.values(),
                                index=electrode_channels[patches.keys()])

    for patch_i in channel_patches:
        patch_i.set_edgecolor(None)
        patch_i.set_alpha(.4)
        patch_i.set_label(None)

    df_channel_centers = get_channel_centers(chip_info_mm)
    q1, q2 = render_plan(axes[1], df_channel_centers, channel_patches,
                         channel_plan, completed_transfers)

    if completed_transfers:
        completed_plan = ([completed_transfers[0]['channels'][0]] +
                          [t['channels'][1] for t in completed_transfers])
    else:
        completed_plan  = []

    missing_transfers = (set(test_channels) - set(completed_plan) -
                         set(channel_plan))
    channel_patches[missing_transfers].map(lambda x: x.set_facecolor(dark_red))

    # Update default legend with passed/failed electrode patches styles.
    axis = axes[1]
    axis.legend()
    handles, labels = axis.get_legend_handles_labels()
    axis.get_legend().remove()
    handles += [mpl.patches.Patch(facecolor=c, alpha=.4)
                for c in (light_green, dark_red, dark_orange)]
    labels += ['Passed electrode', 'Failed electrode', 'Skipped electrode']
    axis.legend(handles=handles, labels=labels, handleheight=2, handlelength=2)
    return axes


def get_channel_centers(chip_info):
    electrode_channels = {e['id']: e['channels'][0]
                          for e in chip_info['electrodes']}

    # Find center of electrode associated with each DropBot channel.
    df_electrode_centers = pd.DataFrame([e['pole_of_accessibility']
                                         for e in chip_info['electrodes']],
                                        index=[e['id'] for e in
                                               chip_info['electrodes']])
    df_electrode_centers.index.name = 'id'
    s_electrode_channels = pd.Series(electrode_channels)
    df_channel_centers = df_electrode_centers.loc[s_electrode_channels.index]
    df_channel_centers.index = s_electrode_channels.values
    df_channel_centers.sort_index(inplace=True)
    df_channel_centers.index.name = 'channel'
    return df_channel_centers


def summarize_results(**kwargs):
    test_info = copy.deepcopy(kwargs)
    test_info['dropbot_version'] = db.__version__
    test_info['dropbot_chip_qc_version'] = __version__
    # Render DropBot system info using `dropbot.self_test` module functions.
    test_info.update({'dropbot':
                      {'%s' % k:
                       re.sub(r'^#(.*)#', r'##\1##',
                              f(kwargs['dropbot'][k]), flags=re.MULTILINE)
                       for k, f in (('system_info',
                                     db.self_test.format_system_info_results),
                                    ('i2c_scan',
                                     db.self_test.format_test_i2c_results))}})

    template = jinja2.Template('''
# DropBot chip quality control test

## Test setup

- **Chip UUID:** `{{ chip_uuid }}`
{% if qr_uuid_path %}
  ![]({{ qr_uuid_path }}){% endif %}
- **`dropbot` version:** `{{ dropbot_version }}`
- **`dropbot-chip-qc` version:** `{{ dropbot_chip_qc_version }}`

## Results

{% if shorts_detected %}
 - **Shorted channels:** `{{ shorts_detected | unique | sort }}`
{%- endif %}
 - **Failed electrodes:** `{{ fail_electrodes }}`
 - **Skipped electrodes:** `{{ skip_electrodes }}`
{% if image_path %}
![]({{ image_path }})
{% endif %}
# DropBot system info

{{ dropbot.system_info }}

{{ dropbot.i2c_scan }}
    ''')
    return template.render(**test_info)


def render_summary(output_path, **kwargs):
    # Create temporary working directory.
    parent_dir = ph.path(tempfile.mkdtemp(prefix='dropbot-chip-qc'))
    output_path = ph.path(output_path).realpath()

    try:
        if 'chip_uuid' in kwargs:
            qr_uuid_img = qrcode.make(kwargs['chip_uuid'].upper())
            qr_uuid_path = parent_dir.joinpath('uuid-qr.png')
            qr_uuid_img.save(qr_uuid_path)
        else:
            qr_uuid_path = None

        if 'chip-info' in kwargs:
            chip_info = kwargs['chip-info']
            # Save chip summary figure to PNG file output.
            axes = draw_results(chip_info, kwargs['channel_plan'],
                                kwargs['completed_transfers'],
                                test_channels=kwargs['test_channels'])
            axis = axes[0]
            fig = axis.get_figure()
            image_path = parent_dir.joinpath('test-result.png')
            fig.savefig(image_path, bbox_inches='tight')
            plt.close(fig)
        else:
            image_path = None

        # Generate Markdown test results summary.
        markdown_summary = summarize_results(image_path=image_path,
                                             qr_uuid_path=qr_uuid_path,
                                             **kwargs)

        # Write test results output to `README.md`
        markdown_path = parent_dir.joinpath('README.md')
        with markdown_path.open('w') as output:
            print >> output, markdown_summary

        # Write template to file for use with `pandoc`.
        template = pkgutil.get_data('dropbot', 'static/templates/'
                                    'SelfTestTemplate.html5')
        template_path = parent_dir.joinpath('SelfTestTemplate.html5')
        template_path.write_text(template)

        # Use `pandoc` to create self-contained `.html` report.
        sp.check_call(['pandoc', markdown_path, '-o', output_path,
                       '--standalone', '--self-contained', '--template',
                       template_path], shell=True, stderr=sp.PIPE)
    finally:
        # Delete temporary working directory.
        parent_dir.rmtree()

    with output_path.open('r') as input_:
        html_data = input_.read().decode('utf8')

    # Inject JSON result data into HTML report.
    cre_results_script = re.compile(r'<script id="results" type="application/json">(.*?</script>)?',
                                    flags=re.DOTALL | re.MULTILINE)

    match = cre_results_script.search(html_data)
    if match:
        # Format JSON with indents.  Works around [`json_tricks`
        # issue][i51].
        #
        # [i51]: https://github.com/mverleg/pyjson_tricks/issues/51
        results = kwargs.copy()
        results.pop('chip-info', None)
        json_data = json_tricks.dumps(results, indent=4)
        html_mod = cre_results_script.sub(r'<script id="results" '
                                          r'type="application/json">%s'
                                          r'</script>' % json_data, html_data)

        output_with_json_path = \
            output_path.parent.joinpath(output_path.namebase +
                                        '-with_json.html')
        with output_with_json_path.open('w') as output:
            output.write(html_mod.encode('utf8'))
    return fig


def get_summary_dict(proxy, chip_info, test_channels, channel_plan,
                     completed_transfers, chip_uuid=None):
    message = {}
    message['dropbot'] = {'system_info': db.self_test.system_info(proxy),
                          'i2c_scan': db.self_test.test_i2c(proxy)}
    message['shorts_detected'] = proxy.detect_shorts()
    message['chip-info'] = chip_info
    message['test_channels'] = test_channels

    completed_transfers = completed_transfers
    if completed_transfers:
        completed_plan = ([completed_transfers[0]['channels'][0]] +
                        [t['channels'][1] for t in completed_transfers])
    else:
        completed_plan  = []

    message['channel_plan'] = channel_plan
    message['completed_transfers'] = completed_transfers

    message['fail_electrodes'] = sorted(set(test_channels) -
                                        set(completed_plan) -
                                        set(channel_plan))
    message['skip_electrodes'] = sorted(set(test_channels)
                                        .intersection(set(channel_plan))
                                        - set(completed_plan))

    if chip_uuid:
        message['chip_uuid'] = chip_uuid
    return message
