import io
import pkgutil
import re
import subprocess as sp
import tempfile

import bs4
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


def draw_results(chip_info, events, axes=None):
    if axes is None:
        fig, axes = plt.subplots(1, 2, figsize=(20, 20))

    # For colors, see: https://gist.github.com/cfobel/fd939073cf13a309d7a9
    dark_green = '#059748'
    light_green = '#90cd97'
    light_blue = '#88bde6'
    dark_orange = '#df5c24'
    dark_red = '#cb2027'

    chip_info_mm = dc.to_unit(chip_info, 'mm')

    electrode_channels = {e['id']: e['channels'][0]
                          for e in chip_info['electrodes']}

    for i, ax in enumerate(axes):
        result = dc.draw(chip_info, ax=ax, unit='mm', labels=(i == 0))
        for id_i, p in result['patches'].items():
            p.set_edgecolor('none')
            p.set_facecolor(light_blue)
        labels = {t.get_text(): t for t in result['axis'].texts}
        for id_i, label_i in labels.items():
            label_i.set_text(electrode_channels[id_i])
        result['patches']

    x_coords = [p[0] for e in chip_info_mm['electrodes'] for p in e['points']]
    y_coords = [p[1] for e in chip_info_mm['electrodes'] for p in e['points']]

    for ax in axes:
        ax.set_xlim(min(x_coords), max(x_coords))
        ax.set_ylim(max(y_coords), min(y_coords))
        ax.set_axis_off()
        ax.set_frame_on(False)

    # Draw QC test route
    # ------------------

    # Find center of electrode associated with each DropBot channel.
    df_electrode_centers = pd.DataFrame([e['pole_of_accessibility']
                                         for e in chip_info_mm['electrodes']],
                                        index=[e['id'] for e in
                                               chip_info_mm['electrodes']])
    df_electrode_centers.index.name = 'id'
    s_electrode_channels = pd.Series(electrode_channels)
    df_channel_centers = df_electrode_centers.loc[s_electrode_channels.index]
    df_channel_centers.index = s_electrode_channels.values
    df_channel_centers.sort_index(inplace=True)
    df_channel_centers.index.name = 'channel'

    axis = result['axis']
    patches = result['patches']
    channel_patches = pd.Series(patches.values(),
                                index=s_electrode_channels[patches.keys()])

    df_events = pd.DataFrame(events)
    df_electrode_events = \
        df_events.loc[df_events.event
                      .isin(['electrode-success',
                             'electrode-fail'])].dropna(axis=1)
    for patch_i in (channel_patches
                    .loc[df_electrode_events.loc[df_electrode_events.event ==
                                                 'electrode-fail', 'target']]):
        patch_i.set_facecolor(dark_red)

    for patch_i in (channel_patches
                    .loc[df_events.loc[df_events.event == 'electrode-skip',
                                       'target'].tolist()]):
        patch_i.set_facecolor(dark_orange)

    for patch_i in (channel_patches
                    .loc[df_electrode_events.loc[df_electrode_events.event ==
                                                 'electrode-success', 'target']]):
        patch_i.set_facecolor(light_green)

    for patch_i in channel_patches:
        patch_i.set_edgecolor(None)
        patch_i.set_alpha(.4)
        patch_i.set_label(None)

    df_electrode_events.loc[:, ['source', 'target']] = \
        df_electrode_events[['source', 'target']].astype(int)
    df_source_centers = df_channel_centers.loc[df_electrode_events.source]
    df_target_centers = df_channel_centers.loc[df_electrode_events.target]

    success_channels = df_electrode_events.loc[df_electrode_events.event ==
                                               'electrode-success',
                                               ['source', 'target']]
    success_channels = (success_channels.source.iloc[:1].tolist() +
                        success_channels.target.tolist())
    df_electrode_events_centers = df_channel_centers.loc[success_channels]
    x = df_electrode_events_centers.x
    y = df_electrode_events_centers.y

    # Draw markers to indicate start and end of test route.
    axis.scatter(x[:1], y[:1], marker='o', s=10 ** 2, edgecolor=dark_orange,
                 linewidth=2, facecolor='none', label='Route start')
    axis.scatter(x[-1:], y[-1:], marker='s', s=15 ** 2, color=dark_orange,
                 linewidth=2, facecolor='none', label='Route end')

    # Draw route over electrodes as sequence of arrows.
    # See: https://stackoverflow.com/a/7543518/345236
    q = axis.quiver(df_source_centers.x, df_source_centers.y,
                    df_target_centers.x.values - df_source_centers.x,
                    df_target_centers.y.values - df_source_centers.y,
                    scale_units='xy', angles='xy',
                    color=[dark_green if e == 'electrode-success'
                           else dark_red for e in df_electrode_events.event])
    # Ensure route is drawn on top layer of plot.
    q.set_zorder(20)

    # Update default legend with passed/failed electrode patches styles.
    axis.legend()
    handles, labels = axis.get_legend_handles_labels()
    axis.get_legend().remove()
    handles += [mpl.patches.Patch(facecolor=c, alpha=.4)
                for c in (light_green, dark_red, dark_orange)]
    labels += ['Passed electrode', 'Failed electrode', 'Skipped electrode']
    axis.legend(handles=handles, labels=labels, handleheight=2, handlelength=2)
    return axes


def summarize_results(events, **kwargs):
    '''
    .. versionchanged:: 0.10.0
        Read software versions from ``test-start`` instead of
        ``test-complete``.  Add ``shorts_detected`` item to render context
        dictionary.
    '''
    test_info = {}
    start_info = [e for e in events if e['event'] == 'test-start'][0]
    bad_electrodes = {'%s_electrodes' % k:
                      sorted(set(int(e['target']) for e in events
                                 if e['event'] == 'electrode-%s' % k))
                      for k in ('fail', 'skip')}
    test_info.update(bad_electrodes)
    test_info.update({'chip_uuid': start_info['uuid']})
    for k in ('dropbot', 'dropbot_chip_qc'):
        test_info['%s_version' % k] = start_info['%s.__version__' % k]
    test_info['shorts_detected'] = sorted(set(c for e in events
                                              if e['event'] ==
                                              'shorts-detected'
                                              for c in e['values']))
    test_info.update(kwargs)
    # Render DropBot system info using `dropbot.self_test` module functions.
    test_info.update({'dropbot':
                      {'%s' % k:
                       re.sub(r'^#(.*)#', r'##\1##',
                              f(start_info['dropbot'][k]), flags=re.MULTILINE)
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
 - **Shorted channels:** `{{ shorts_detected }}`
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


def render_summary(events, output_path, svg_source=None):
    # Create temporary working directory.
    parent_dir = ph.path(tempfile.mkdtemp(prefix='dropbot-chip-qc'))

    if svg_source is None:
        svg_data = pkgutil.get_data('dropbot',
                                    'static/SCI-BOTS 90-pin array/device.svg')
        svg_source = io.BytesIO(svg_data)

    try:
        start_events = [e for e in events if e.get('event') == 'test-start']
        if start_events and 'uuid' in start_events[0]:
            qr_uuid_img = qrcode.make(start_events[0]['uuid'].upper())
            qr_uuid_path = parent_dir.joinpath('uuid-qr.png')
            qr_uuid_img.save(qr_uuid_path)
        else:
            qr_uuid_path = None

        if start_events and 'chip-info' in start_events[0]:
            chip_info = start_events[0]['chip-info']
            # Save chip summary figure to PNG file output.
            axes = draw_results(chip_info, events)
            axis = axes[0]
            fig = axis.get_figure()
            image_path = parent_dir.joinpath('test-result.png')
            fig.savefig(image_path, bbox_inches='tight')
            plt.close(fig)

        # Generate Markdown test results summary.
        markdown_summary = summarize_results(events, image_path=image_path,
                                             qr_uuid_path=qr_uuid_path)

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
        html_data = input_.read()

    # Inject JSON result data into HTML report.
    soup = bs4.BeautifulSoup(html_data, 'lxml')
    results_script = soup.select_one('script#results')
    # Format JSON with indents.  Works around [`json_tricks`
    # issue][i51].
    #
    # [i51]: https://github.com/mverleg/pyjson_tricks/issues/51
    json_data = json_tricks.dumps(events, indent=4)
    results_script.string = bs4.NavigableString(json_data)
    with output_path.open('w') as output:
        output.write(unicode(soup).encode('utf8'))
    return fig
