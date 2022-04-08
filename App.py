# Copyright 2019 (c) Michael Cook <michael@waxrat.com>. All rights reserved.
import sys
import os
import logging
import argparse
import time
from typing import Tuple, Dict, List, Set, Optional
from stat import S_ISREG, S_ISBLK
from PyQt5 import QtWidgets, QtGui, QtCore
from PyQt5.QtCore import Qt, QPoint
from mcook import gmk
import MainWindow
try:
    from typing import Final
except ImportError:
    from typing import Any
    Final = Any                 # type: ignore

SCRIPT_DIR: Final = os.path.abspath(os.path.dirname(sys.argv[0]))

parser = argparse.ArgumentParser(description="""

Watch processes as they progress through file I/O operations.

""")
parser.add_argument('--ignore', '-i', action='append', default=[], help="""
Comma-separated list of commands to ignore
""")
parser.add_argument('--debug', action='store_true')
OPTS = parser.parse_args()
del parser

logging.basicConfig(level=logging.DEBUG if OPTS.debug else logging.INFO,
                    format='%(name)s: %(levelname)s: %(message)s')
LOGGER: Final = logging.getLogger('QtProgress')

IGNORED_COMMANDS = set(','.join(OPTS.ignore).split(','))

# ------------------------------------------------------------------------------

Item: Final = QtWidgets.QTableWidgetItem

GREY: Final = QtGui.QColor(200, 200, 200)
WHITE: Final = QtGui.QColor(255, 255, 255)
YELLOW: Final = QtGui.QColor(0xff, 0xff, 0xdd)  # light yellow

# How often to check for changed proc files
UPDATE_MSEC: Final = 2000

# After this many periods (UPDATE_MSEC), if a given proc file hasn't
# changed, delete it from the display.
KEEP_COUNTDOWN: Final = 120

class File:
    def __init__(self, name: str, pos: int, size: int, timestamp: float) -> None:
        self.name = name
        self.pos: Optional[int] = pos
        self.size = size
        self.first_pos = pos
        self.first_size = size
        self.first_timestamp = timestamp
        self.table_row: Optional[int] = None
        self.keep_countdown = KEEP_COUNTDOWN

    def __str__(self) -> str:
        return f'File({self.name},{self.pos},{self.size})'

FdDevIno = Tuple[int, int, int]
Files = Dict[FdDevIno, File]
FileSet = Set[File]

class Process:
    def __init__(self, pid: int, command: str, files: Files) -> None:
        self.pid = pid          # process identifier
        self.command = command  # name of the process command
        self.files = files

    def __str__(self) -> str:
        return f'Process({self.pid},{self.command})'

Processes = List[Process]

def get_procs() -> Processes:
    """
    Take a snapshot of /proc.

    Returns a list of Process objects.
    """

    procs = []
    timestamp = time.time()
    for pid in os.listdir('.'):
        if not pid[0].isdigit():
            continue

        fddir = pid + '/fd/'
        try:
            fds = os.listdir(fddir)
        except OSError as exc:
            LOGGER.debug('pid %s: skip %s', pid, exc)
            continue

        try:
            with open(pid + '/comm') as f:
                command = f.read().rstrip('\n')
        except IOError as exc:
            LOGGER.debug('pid %s: skip %s', pid, exc)
            continue

        fdmap = {}
        for fd in fds:
            try:
                fdfile = fddir + fd
                st = os.stat(fdfile)

                if not S_ISREG(st.st_mode) and not S_ISBLK(st.st_mode):
                    # LOGGER.debug('pid %s, fd %s: not regular or block', pid, fd)
                    continue

                name = os.readlink(fdfile)
                LOGGER.debug('pid %s, fd %s: name %r', pid, fd, name)

                size = st.st_size
                pos = 0
                with open(pid + '/fdinfo/' + fd, 'rt') as f:
                    for line in f:
                        LOGGER.debug('pid %s, fd %s: fdinfo: %r', pid, fd, line)
                        if line.startswith('pos:'):
                            pos = int(line[4:])
                            break
                LOGGER.debug('pid %s, fd %s: pos %s of %s', pid, fd, pos, size)

                fdmap[int(fd), st.st_dev, st.st_ino] = \
                    File(name=name, pos=pos, size=size, timestamp=timestamp)

            except OSError as exc:
                LOGGER.debug('pid %s, fd %s: skip: %s', pid, fd, exc)

        procs.append(Process(pid=int(pid), command=command, files=fdmap))
    return procs

def percentage(n: Optional[int], d: int) -> str:
    """
    Returns a string like '12.3%' from numerator N and denominator D
    """
    if n is None:
        return '?'
    if d == 0:
        if n == 0:
            return '0%'
        return '?'
    return '{0:.1f}%'.format(100.0 * n / d).replace('.0', '')

# ------------------------------------------------------------------------------

PidCommandFdDevInoName = Tuple[int, str, int, int, int, str]

class ThisAppMainWindow(QtWidgets.QMainWindow, MainWindow.Ui_MainWindow):

    proc_files: Dict[PidCommandFdDevInoName, File] = {}
    last_hilite: FileSet = set()

    def __init__(self) -> None:
        QtWidgets.QMainWindow.__init__(self)
        MainWindow.Ui_MainWindow.__init__(self)

        super().setupUi(self)

        self.pushButton_hide.clicked.connect(self.hide_all_rows)
        self.pushButton_unignore.clicked.connect(self.unignore)

        tab = self.mainTable

        tab.setContextMenuPolicy(Qt.CustomContextMenu)
        tab.customContextMenuRequested.connect(self.show_table_context_menu)

        self.pushButton_quit.clicked.connect(sys.exit)

        tab.setRowCount(0)

        h = tab.horizontalHeader()
        col = 0

        # when
        h.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)
        col += 1

        # position%
        h.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)
        col += 1

        # position
        h.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)
        col += 1

        # size
        h.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)
        col += 1

        # rate
        h.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)
        col += 1

        # remaining
        h.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)
        col += 1

        # command
        h.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)
        col += 1

        # file name
        h.setSectionResizeMode(col, QtWidgets.QHeaderView.Stretch)
        col += 1

        self.update_table()

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(UPDATE_MSEC)

        self.set_hide_button()
        self.set_unignore_button()

        self.show()

    def show_table_context_menu(self, position: QPoint) -> None:
        item = self.mainTable.itemAt(position)
        if item is None:
            return

        row = item.row()
        column = item.column()
        LOGGER.debug('at %s,%s', row, column)

        for it, proc_file in self.proc_files.items():
            if row == proc_file.table_row:
                command = it[1]
                break
        else:
            LOGGER.error('No row %s', row)
            return

        menu = QtWidgets.QMenu()
        ignoreAction = menu.addAction(f'Ignore: {command}')
        action = menu.exec_(self.mainTable.mapToGlobal(position))
        if action == ignoreAction:
            LOGGER.debug('Ignore: %r', command)
            self.ignore_command(command)
        else:
            LOGGER.debug('Other: %r', action)

    def keyPressEvent(self, e: QtGui.QKeyEvent) -> None:
        key = e.key()
        LOGGER.debug('keyPressEvent %s %r', key, e)

        # If a table cell is selected, unselect it.
        if key == Qt.Key_Escape:
            self.mainTable.setCurrentCell(-1, -1)

    def update_row(self, pid: int, command: str, fd: int, proc_file: File) -> None:
        now = time.time()
        tab = self.mainTable
        proc_file.keep_countdown = KEEP_COUNTDOWN

        row = proc_file.table_row
        if row is None:
            # Add the file to the table -- insert at top
            row = 0
            tab.insertRow(row)
            for pf in self.proc_files.values():
                if pf.table_row is not None:
                    pf.table_row += 1
            proc_file.table_row = row

        col = 0

        closed = proc_file.pos is None

        # when
        i = Item(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now)))
        i.setTextAlignment(int(Qt.AlignCenter))
        if closed:
            i.setForeground(GREY)
        tab.setItem(row, col, i)
        col += 1

        # position%
        i = Item('-' if closed
                 else percentage(proc_file.pos, proc_file.size))
        i.setTextAlignment(int(Qt.AlignCenter))
        if closed:
            i.setForeground(GREY)
        tab.setItem(row, col, i)
        col += 1

        # position
        i = Item('-' if closed or proc_file.pos is None
                 else gmk(proc_file.pos))
        i.setTextAlignment(int(Qt.AlignCenter))
        if closed:
            i.setForeground(GREY)
        tab.setItem(row, col, i)
        col += 1

        # size
        i = Item(gmk(proc_file.size))
        i.setTextAlignment(int(Qt.AlignCenter))
        if closed:
            i.setForeground(GREY)
        tab.setItem(row, col, i)
        col += 1

        # rate, remaining
        rate = '-'
        more_time = '-'
        if proc_file.pos is not None:
            elapsed = now - proc_file.first_timestamp
            if elapsed != 0:
                bytes_per_sec = (proc_file.pos - proc_file.first_pos) / elapsed
                if bytes_per_sec > 0:
                    rate = gmk(bytes_per_sec) + 'B/s'
                    more_bytes = proc_file.size - proc_file.pos
                    if more_bytes > 0:
                        s = int(more_bytes / bytes_per_sec)
                        more_time = '{0:d}:{1:02d}'.format(s // 60, s % 60)

        i = Item(rate)
        i.setTextAlignment(int(Qt.AlignCenter))
        if closed:
            i.setForeground(GREY)
        tab.setItem(row, col, i)
        col += 1

        i = Item(more_time)
        i.setTextAlignment(int(Qt.AlignCenter))
        if closed:
            i.setForeground(GREY)
        tab.setItem(row, col, i)
        col += 1

        # command
        i = Item(command)
        i.setTextAlignment(int(Qt.AlignCenter))
        i.setToolTip(f'PID {pid}')
        if closed:
            i.setForeground(GREY)
        tab.setItem(row, col, i)
        col += 1

        # file name
        i = Item(os.path.basename(proc_file.name))
        i.setToolTip(f'{fd} -> {proc_file.name}')
        i.setTextAlignment(int(Qt.AlignLeft | Qt.AlignVCenter))
        if closed:
            i.setForeground(GREY)
        tab.setItem(row, col, i)
        col += 1

    def update_table(self) -> None:
        closed = set(self.proc_files.keys())
        hilite: FileSet = set()

        for proc in get_procs():
            if proc.command in IGNORED_COMMANDS:
                continue

            for (fd, dev, ino), new_proc_file in proc.files.items():
                it = proc.pid, proc.command, fd, dev, ino, new_proc_file.name
                closed.discard(it)

                proc_file = self.proc_files.get(it)
                if not proc_file:
                    # New file. Add it to proc_files, but we won't add it to
                    # the table yet -- wait until the position changes.
                    self.proc_files[it] = new_proc_file
                    continue

                if proc_file.pos == new_proc_file.pos and \
                   proc_file.size == new_proc_file.size:
                    continue

                proc_file.pos = new_proc_file.pos
                proc_file.size = new_proc_file.size

                self.update_row(proc.pid, proc.command, fd, proc_file)
                hilite.add(proc_file)

        # Check for files that are now gone (closed)
        for it in closed:
            proc_file = self.proc_files[it]
            if proc_file.table_row is None:
                del self.proc_files[it]
                continue
            if proc_file.pos is None:
                continue
            LOGGER.debug('closed: %s %s', it, proc_file)
            proc_file.pos = None
            pid, command, fd, dev, ino, _file_name = it
            self.update_row(pid, command, fd, proc_file)
            hilite.add(proc_file)

        # Decrement keep_count for each row and delete the row if the count
        # reaches zero.  Don't delete the proc_files entry, though; if later
        # there's new activity on this proc_file, we'll re-add the row and
        # pick up where we left off.
        for proc_file in self.proc_files.values():
            row = proc_file.table_row
            if row is None:
                continue
            proc_file.keep_countdown -= 1
            LOGGER.debug('countdown %s, row %s, file %s',
                         proc_file.keep_countdown,
                         proc_file.table_row,
                         proc_file.name)
            if proc_file.keep_countdown > 0:
                continue
            proc_file.table_row = None
            self.remove_row(row)

        # Adjust the row hilighting
        for proc_file in self.last_hilite - hilite:
            self.hilite_row(proc_file.table_row, False)
        for proc_file in hilite:
            self.hilite_row(proc_file.table_row, True)
        self.last_hilite = hilite

        self.set_hide_button()
        self.mainTable.setCurrentCell(-1, -1)

    def remove_row(self, row: int) -> None:
        self.mainTable.removeRow(row)
        # Adjust table_row for all rows after this one
        for pf in self.proc_files.values():
            if pf.table_row is not None and pf.table_row > row:
                pf.table_row -= 1

    def hilite_row(self, row: Optional[int], hilite: bool) -> None:
        if row is None:
            return
        tab = self.mainTable
        color = YELLOW if hilite else WHITE
        for col in range(tab.columnCount()):
            i = tab.item(row, col)
            if not i:
                LOGGER.error('No cell at %s,%s', row, col)
                continue
            i.setBackground(color)

    def tick(self) -> None:
        LOGGER.debug('Tick...')
        self.update_table()
        LOGGER.debug('Tick...done')

    def hide_all_rows(self) -> None:
        """
        Hide all rows.  If there's any activity later, the rows will reappear
        """
        self.mainTable.setRowCount(0)
        self.last_hilite = set()
        for proc_file in self.proc_files.values():
            proc_file.table_row = None
        self.set_hide_button()

    def ignore_command(self, command_to_ignore: str) -> None:
        IGNORED_COMMANDS.add(command_to_ignore)
        for it, proc_file in self.proc_files.items():
            if proc_file.table_row is None:
                continue
            _pid, command, _fd, _dev, _info, _name = it
            if command != command_to_ignore:
                continue

            row = proc_file.table_row
            proc_file.table_row = None
            self.remove_row(row)
        self.set_unignore_button()

    def unignore(self) -> None:
        global IGNORED_COMMANDS
        IGNORED_COMMANDS = set()
        self.set_unignore_button()

    def set_hide_button(self) -> None:
        self.pushButton_hide.setEnabled(self.mainTable.rowCount() != 0)

    def set_unignore_button(self) -> None:
        but = self.pushButton_unignore
        if IGNORED_COMMANDS:
            but.setEnabled(True)
            but.setToolTip('\n'.join(sorted(IGNORED_COMMANDS,
                                            key=lambda x: x.lower())))
        else:
            but.setEnabled(False)
            but.setToolTip('')

def main() -> None:
    os.chdir('/proc')

    app = QtWidgets.QApplication(['QtProgress'])
    app.setStyle(QtWidgets.QStyleFactory.create('Fusion'))  # type: ignore
    app.setWindowIcon(QtGui.QIcon(os.path.join(SCRIPT_DIR, 'icon.png')))
    _ui = ThisAppMainWindow()   # noqa: F841 local variable assigned to but never used
    sys.exit(app.exec_())

main()
