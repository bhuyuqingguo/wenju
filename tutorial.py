"""Read the built-in lessons and play their prerecorded narration."""
import json
from pathlib import Path
import shutil
import sys
import tempfile

from qt_compat import QObject, Property, QProcess, Signal, Slot, constant_property, process_failed


class Tutorial(QObject):
    statusChanged = Signal()

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.directory = Path(root) / 'core' / 'tutorial'
        try:
            self._chapters = json.loads((self.directory / 'chapters.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self._chapters = []
        self._status = ''
        self._player = QProcess(self)
        self._player.errorOccurred.connect(self._audio_error)
        self._player.finished.connect(self._audio_finished)
        self._stopping = False

    @constant_property('QVariantList')
    def chapters(self):
        return self._chapters

    @Property(str, notify=statusChanged)
    def status(self):
        return self._status

    def _set_status(self, text):
        self._status = text
        self.statusChanged.emit()

    def copy_case(self, index, destination):
        if not 0 <= index < len(self._chapters):
            raise ValueError('未找到教学章节。')
        case = self._chapters[index].get('case')
        if not case:
            raise ValueError('本章没有练习案例。')
        source = self.directory / 'cases' / case['directory']
        if not (source / case['file']).is_file():
            raise ValueError('练习案例缺失，请检查程序是否完整解压。')
        destination.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix=case['directory'] + '-', dir=str(destination)))
        shutil.copytree(source, folder, dirs_exist_ok=True)
        return case['action'], folder / case['file']

    def _audio_error(self, error):
        if process_failed(error):
            self._set_status('无法启动语音播放器。你仍可阅读本章的文字步骤。')

    def _audio_finished(self, exit_code, _exit_status):
        if exit_code and not self._stopping:
            self._set_status('语音播放失败，请检查音频设备。')

    @Slot()
    def stop(self):
        if sys.platform == 'win32':
            import winsound
            winsound.PlaySound(None, 0)
        elif self._player.state() != QProcess.NotRunning:
            self._stopping = True
            self._player.kill()
            self._player.waitForFinished(500)
            self._stopping = False
        self._set_status('')

    @Slot(int)
    def play(self, index):
        self.stop()
        if not 0 <= index < len(self._chapters):
            return
        audio = self.directory / (self._chapters[index]['id'] + '.wav')
        if not audio.is_file():
            self._set_status('本章语音文件缺失，请检查程序是否完整解压。')
            return
        if sys.platform == 'win32':
            import winsound
            try:
                winsound.PlaySound(str(audio), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            except RuntimeError:
                self._set_status('语音播放失败，请检查音频设备。')
            return
        for program, flags in (('paplay', []), ('pw-play', []), ('aplay', ['-q'])):
            executable = shutil.which(program)
            if executable:
                self._player.start(executable, flags + [str(audio)])
                return
        self._set_status('系统缺少语音播放器。你仍可阅读本章的文字步骤。')
