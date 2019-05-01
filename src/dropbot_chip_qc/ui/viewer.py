from PySide2 import QtGui, QtCore, QtWidgets
import cv2

from .invoker import Invoker


class ImageViewer(QtWidgets.QGraphicsView):
    '''View ``QtGui.QPixmap``; automatically fit in frame with pan and zoom.

    See: https://stackoverflow.com/a/35514531/345236
    '''
    imageClicked = QtCore.Signal(QtCore.QPoint)

    def __init__(self, parent):
        super(ImageViewer, self).__init__(parent)
        self._zoom = 0
        self._empty = True
        self._scene = QtWidgets.QGraphicsScene(self)
        self._photo = QtWidgets.QGraphicsPixmapItem()
        self._scene.addItem(self._photo)
        self.setScene(self._scene)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QtGui.QBrush(QtGui.QColor(30, 30, 30)))
        self.setFrameShape(QtWidgets.QFrame.NoFrame)

    def hasImage(self):
        return not self._empty

    def fitInView(self, scale=True):
        rect = QtCore.QRectF(self._photo.pixmap().rect())
        if not rect.isNull():
            self.setSceneRect(rect)
            if self.hasImage():
                unity = self.transform().mapRect(QtCore.QRectF(0, 0, 1, 1))
                self.scale(1 / unity.width(), 1 / unity.height())
                viewrect = self.viewport().rect()
                scenerect = self.transform().mapRect(rect)
                factor = min(viewrect.width() / scenerect.width(),
                             viewrect.height() / scenerect.height())
                self.scale(factor, factor)
            self._zoom = 0

    def setPhoto(self, pixmap=None):
        if pixmap and not pixmap.isNull():
            self._empty = False
            self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
            self._photo.setPixmap(pixmap)
        else:
            self._empty = True
            self.setDragMode(QtWidgets.QGraphicsView.NoDrag)
            self._photo.setPixmap(QtGui.QPixmap())

    def wheelEvent(self, event):
        if self.hasImage():
            if event.angleDelta().y() > 0:
                factor = 1.125
                self._zoom += 1
            else:
                factor = 0.875
                self._zoom -= 1
            if self._zoom == 0:
                self.fitInView()
            else:  # self._zoom > 0:
                self.scale(factor, factor)

    def toggleDragMode(self):
        if self.dragMode() == QtWidgets.QGraphicsView.ScrollHandDrag:
            self.setDragMode(QtWidgets.QGraphicsView.NoDrag)
        elif not self._photo.pixmap().isNull():
            self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)

    def mousePressEvent(self, event):
        if self._photo.isUnderMouse():
            self.imageClicked.emit(QtCore.QPoint(event.pos()))
        super(ImageViewer, self).mousePressEvent(event)


class QCVideoViewer(ImageViewer):
    '''Show latest frame received from a ``frame-ready`` blinker signal.
    '''
    def __init__(self, parent, signals):
        super(QCVideoViewer, self).__init__(parent)
        self._signals = signals
        self._invoker = Invoker()
        signals.signal('frame-ready').connect(self.on_frame_ready)

    def on_frame_ready(self, sender, **record):
        frame = record['frame']
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        def draw_frame(rgb_frame):
            image = QtGui.QImage(rgb_frame, rgb_frame.shape[1],
                                 rgb_frame.shape[0],
                                 rgb_frame.shape[1] * 3,
                                 QtGui.QImage.Format_RGB888)
            pix = QtGui.QPixmap(image)
            self.setPhoto(pix)

        self._invoker.invoke(draw_frame, rgb_frame)
