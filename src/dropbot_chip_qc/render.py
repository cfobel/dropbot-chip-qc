import io
import pkgutil
import re
import subprocess as sp
import tempfile

import bs4
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


def draw_results(svg_source, events, axes=None):
    if axes is None:
        fig, axes = plt.subplots(1, 2, figsize=(20, 20))

    db.chip.draw(svg_source, ax=axes[0])
    result = db.chip.draw(svg_source, labels=False, ax=axes[1])

    for ax in axes:
        ax.set_frame_on(False)
        ax.set_axis_off()

    # Draw QC test route
    # ------------------

    df_shapes = result['df_shapes']

    # Find center of electrode associated with each DropBot channel.
    df_electrode_centers = df_shapes.groupby('id')[['x', 'y']].mean()
    df_channel_centers = pd.DataFrame(df_electrode_centers.values,
                                      index=result['electrode_channels']
                                      .loc[df_electrode_centers.index],
                                      columns=['x', 'y'])
    df_channel_centers.index.name = 'channel'

    axis = result['axis']

    # For colors, see: https://gist.github.com/cfobel/fd939073cf13a309d7a9
    dark_green = '#059748'
    light_green = '#90cd97'
    dark_orange = '#df5c24'
    dark_red = '#cb2027'

    df_events = pd.DataFrame(events)
    df_electrode_events = \
        df_events.loc[df_events.event
                      .isin(['electrode-success',
                             'electrode-fail'])].dropna(axis=1)
    for patch_i in (result['channel_patches']
                    .loc[df_electrode_events.loc[df_electrode_events.event ==
                                                 'electrode-fail', 'target']]):
        patch_i.set_facecolor(dark_red)

    for patch_i in (result['channel_patches']
                    .loc[df_electrode_events.loc[df_electrode_events.event ==
                                                 'electrode-success', 'target']]):
        patch_i.set_facecolor(light_green)

    for patch_i in result['channel_patches']:
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
                for c in (light_green, dark_red)]
    labels += ['Passed electrode', 'Failed electrode']
    axis.legend(handles=handles, labels=labels, handleheight=2, handlelength=2)
    return axes


def summarize_results(events, **kwargs):
    df_events = pd.DataFrame(events)
    test_info = df_events.loc[df_events.event == 'test-complete',
                              ['__version__',
                               'failed_electrodes']].iloc[-1].to_dict()
    start_info = df_events.loc[df_events.event ==
                               'test-start'].dropna(axis=1).iloc[-1].to_dict()

    test_info.update({'chip_uuid': start_info['uuid']})
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
- **`dropbot-chip-qc` version:** `{{ __version__ }}`

## Results

**Failed electrodes:** `{{ failed_electrodes }}`
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
        # Save chip summary figure to PNG file output.
        axes = draw_results(svg_source, events)
        axis = axes[0]
        fig = axis.get_figure()
        image_path = parent_dir.joinpath('test-result.png')
        fig.savefig(image_path, bbox_inches='tight')
        plt.close(fig)

        start_events = [e for e in events if e.get('event') == 'test-start']
        if start_events and 'uuid' in start_events[0]:
            qr_uuid_img = qrcode.make(start_events[0]['uuid'].upper())
            qr_uuid_path = parent_dir.joinpath('uuid-qr.png')
            qr_uuid_img.save(qr_uuid_path)
        else:
            qr_uuid_path = None

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
