'''
Copyright 2012 @chfoo (stackoverflow.com), https://stackoverflow.com/a/12127115/345236
Copyright 2019 Christian Fobel (christian@sci-bots.com)

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.


.. versionadded:: X.X.X
'''
from PySide2 import QtCore


class InvokeEvent(QtCore.QEvent):
    EVENT_TYPE = QtCore.QEvent.Type(QtCore.QEvent.registerEventType())

    def __init__(self, fn, *args, **kwargs):
        QtCore.QEvent.__init__(self, InvokeEvent.EVENT_TYPE)
        self.fn = fn
        self.args = args
        self.kwargs = kwargs


class Invoker(QtCore.QObject):
    '''Easy way to schedule code to run in Qt UI thread.

    Equivalent to PyGObject's `GLib.idle_add()`.

    Example
    -------

    >>> from dropbot_chip_qc.ui.invoker import Invoker
    >>>
    >>> invoker = Invoker()
    >>> # Queue `my_function(*my_args, **my_kwargs)` execution in Qt UI thread.
    >>> invoker.invoke(my_function, *my_args, **my_kwargs)
    '''
    def event(self, event):
        event.fn(*event.args, **event.kwargs)

        return True

    def invoke(self, fn, *args, **kwargs):
        QtCore.QCoreApplication.postEvent(self, InvokeEvent(fn, *args,
                                                            **kwargs))
