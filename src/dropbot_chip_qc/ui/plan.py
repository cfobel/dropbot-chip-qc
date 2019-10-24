# -*- coding: utf-8 -*-
'''
.. versionadded:: v0.12.0
'''
from __future__ import (print_function, absolute_import, division,
                        unicode_literals)
import collections
import functools as ft
import itertools as it

from dropbot.threshold_async import TransferTimeout, actuate, test_steady_state_
from dropbot.move import window
from logging_helpers import caller_name
import networkx as nx
import pandas as pd
import si_prefix as si
import trollius as asyncio


class OrphanChannelError(Exception):
    '''
    No path from last successful channel and remaining channels in the
    channel plan.
    '''
    def __init__(self, root_channel, unreachable_channels, *args, **kwargs):
        super(OrphanChannelError, self).__init__(*args, **kwargs)
        self.root_channel = root_channel
        self.unreachable_channels = unreachable_channels

    def __str__(self):
        return unicode(self)

    def __unicode__(self):
        return ('There is no path between channel `%d` and the following '
                'channels in the remaining channel plan: `%s`' %
                (self.root_channel, self.unreachable_channels))


class TransferFailed(Exception):
    def __init__(self, channel_plan, completed_transfers, exception):
        self.channel_plan = channel_plan
        self.completed_transfers = completed_transfers
        self.exception = exception


def unique(seq):
    for i, (a, b) in enumerate(window(seq, 2)):
        if i == 0:
            yield a
        if a != b:
            yield b


def create_channel_plan(channels_graph, waypoints, loop=True):
    '''
    Parameters
    ----------
    channels_graph : networkx.Graph
    waypoints : list
    loop : bool, optional
    '''
    channel_plan = list(it.chain(*(nx.shortest_path(channels_graph, a, b)
                                   for a, b in window(waypoints, 2))))
    if loop:
        channel_plan += nx.shortest_path(channels_graph, waypoints[-1], waypoints[0])
    return unique(channel_plan)


def reroute_plan(waypoints, channels_graph, channel_plan, completed_plan):
    '''
    Attempt to reroute around first channel in channel plan.

    In other words::
     - remove channel from connection graph
     - remove channel from plan
     - remove completed channels from waypoints
     - add last completed channel as first waypoint
     - add next channel in channel plan as second waypoint
     - create a new channel plan


    TODO - prune plan if removed channel makes waypoint channel(s) inaccessible.
    '''
    revised_plan = _reroute_plan(waypoints, channels_graph, channel_plan,
                                    completed_plan)
    return revised_plan


def _reroute_plan(waypoints, channels_graph, channel_plan, completed_plan):
    completed_channels = set(completed_plan)
    channel_plan_i = list(channel_plan)
    channels_graph_i = channels_graph.copy()
    removed_channel = channel_plan_i.pop(0)
    print('Removing channel `%s` from plan.' % removed_channel)
    channels_graph_i.remove_node(removed_channel)

    subgraphs_i = list(nx.connected_component_subgraphs(channels_graph_i))

    # Find subgraph containing last successfully transferred channel.
    accessible_subgraph_i = next(s for s in subgraphs_i
                                 if completed_plan[-1] in s)
    subgraphs_i.remove(accessible_subgraph_i)
    orphan_channels_i = set(it.chain(*(s.nodes for s in subgraphs_i)))
    untestable_channels_i = orphan_channels_i - completed_channels
    # if untestable_channels_i:
        # raise OrphanChannelError(completed_plan[-1],
                                 # [c for c in channel_plan_i
                                  # if c in untestable_channels_i])
    waypoints_i = [w for w in waypoints
                   if w not in completed_channels
                   and w not in untestable_channels_i
                   and w != removed_channel]
    waypoints_i.insert(0, completed_plan[-1])
    waypoints_i.insert(1, next(c for c in channel_plan_i if c not in
                               untestable_channels_i and c != removed_channel))
    waypoints_i.append(waypoints[0])
    channel_plan_i = list(create_channel_plan(channels_graph_i, waypoints_i))
    del channel_plan_i[channel_plan_i.index(waypoints[0]) + 1:]
    return channel_plan_i


@asyncio.coroutine
def _next_transfer(channel_plan, completed_transfers, co_transfer, n=2):
    transfer_channels = channel_plan[:n]
    result = yield asyncio.From(co_transfer(transfer_channels))
    raise asyncio.Return(channel_plan[1:], completed_transfers +
                         [{'channels': transfer_channels, 'result': result}])


@asyncio.coroutine
def transfer_windows(signals, channel_plan, completed_transfers,
                     co_transfer, n=2):
    def on_transfer_complete(sender, **message):
        transfer_i = message['completed_transfers'][-1]
        print('\r%-100s' % ('completed transfer `%s` to `%s`' %
                            (transfer_i['channels'][:-1],
                             transfer_i['channels'][1:])), end='')

    signals.signal('transfer-complete').connect(on_transfer_complete)

    channel_plan_i = list(channel_plan)

    while len(channel_plan_i) > 1:
        try:
            channel_plan_i, completed_transfers = yield asyncio\
                .From(_next_transfer(channel_plan=channel_plan_i,
                                     completed_transfers=completed_transfers,
                                     co_transfer=co_transfer, n=n))
        except Exception as exception:
            raise TransferFailed(channel_plan_i, completed_transfers,
                                 exception)
        else:
            signals.signal('transfer-complete')\
                .send(caller_name(0),
                      channel_plan=channel_plan_i,
                      completed_transfers=completed_transfers)
    channel_plan_i = []
    result = dict(channel_plan=channel_plan_i,
                  completed_transfers=completed_transfers)
    signals.signal('test-complete').send(caller_name(0), **result)
    raise asyncio.Return(result)



@asyncio.coroutine
def transfer_liquid(aproxy, channels, **kwargs):
    '''
    Transfer liquid from tail n-1 channels to head n-1 channels.

        xxxx... -> ...xxxx

    where ``x`` denotes liquid and ``.`` denotes an empty electrode.

    This is accomplished through two separate actuations::

     1. Actuate all but the **last** channel in ``channels``.
     2. Actuate all but the **first** channel in ``channels``.

    Actuation **(1)** is applied until a steady-state capacitance is reached.
    At this point, the measured capacitance is recorded as a target threshold.
    Actuation **(2)** is then applied until the target threshold capacitance
    from actuation **(1)** is reached.
    '''
    messages_ = []

    try:
        tail_channels_i = list(channels[:-1])
        route_i = list(it.chain(*(c if isinstance(c, collections.Sequence)
                                  else [c] for c in tail_channels_i)))
        print('\r%-50s' % ('Wait for steady state: %s' % list(route_i)),
              end='')
        messages = yield asyncio\
            .From(actuate(aproxy, route_i, ft.partial(test_steady_state_,
                                                      **kwargs)))
        messages_.append({'channels': tuple(route_i),
                          'messages': messages})
        target_capacitance_i = ((float(len(channels) - 1) / len(channels))
                                * messages[-1]['new_value'])

        head_channels_i = list(channels[1:])
        print('\r%-50s' % ('Wait for target capacitance of: %sF' %
                           si.si_format(target_capacitance_i)), end='')
        route_i = list(it.chain(*(c if isinstance(c, collections.Sequence)
                                  else [c] for c in head_channels_i)))

        def test_threshold(messages):
            df = pd.DataFrame(messages[-5:])
            return df.new_value.median() >= target_capacitance_i

        messages = yield asyncio\
            .From(actuate(aproxy, route_i, test_threshold))
        messages_.append({'channels': tuple(route_i),
                          'messages': messages})
    except (asyncio.CancelledError, asyncio.TimeoutError):
        raise TransferTimeout(channels)

    raise asyncio.Return(messages_)
