import sys
import os
import json
import shutil
import subprocess
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QLineEdit, QComboBox,
                             QFileDialog, QMessageBox, QGroupBox,
                             QInputDialog, QTextEdit, QTabWidget, QProgressBar, QSplitter, QDialog, QStyle, QSpinBox,
                             QSizePolicy)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSettings, QUrl, QTranslator, QLocale
from PyQt5.QtGui import QDesktopServices, QTextCursor, QDragEnterEvent, QDropEvent, QPixmap, QColor, QPainter, QIcon
import qdarkstyle
from qdarkstyle.light.palette import LightPalette
from tools.loudness_normalization_tab import LoudnessNormalizationTab
from tools.slice_audio_tab import SliceAudioTab
from tools.analysis_tab import FapAnalysisTab
import resources_rc
import tempfile
import multiprocessing
import queue
from multiprocessing import Pool, Manager

FORMAT_PARAMS = {
    'mp3': {
        'bitrate': ['320k', '256k', '192k', '128k', '64k'],
        'sample_rate': ['与源相同', '48000', '44100', '22050', '16000', '8000'],
        'bits': ['与源相同'],
        'channels': ['与源相同', '单声道', '立体声']
    },
    'flac': {
        'bitrate': ['与源相同'],
        'sample_rate': ['与源相同', '44100', '48000', '88200', '96000', '192000', '自定义'],
        'bits': ['与源相同', '16', '24'],
        'channels': ['与源相同', '单声道', '立体声']
    },
    'wav': {
        'bitrate': ['与源相同'],
        'sample_rate': ['与源相同', '44100', '48000', '88200', '96000', '192000', '自定义'],
        'bits': ['与源相同', '16', '24', 'float'],
        'channels': ['与源相同', '单声道', '立体声']
    },
    'aac': {
        'bitrate': ['320k', '256k', '192k', '128k', '64k', '自定义'],
        'sample_rate': ['与源相同', '8000', '16000', '22050', '44100', '48000', '88200', '96000'],
        'bits': ['与源相同'],
        'channels': ['与源相同', '单声道', '立体声']
    },
    'ogg': {
        'bitrate': ['320k', '256k', '192k', '128k', '64k', '自定义'],
        'sample_rate': ['与源相同', '44100', '48000'],
        'bits': ['与源相同'],
        'channels': ['与源相同', '单声道', '立体声']
    },
    'opus': {
        'bitrate': ['320k', '256k', '192k', '128k', '64k', '自定义'],
        'sample_rate': ['与源相同', '48000', '24000', '16000', '8000'],
        'bits': ['与源相同'],
        'channels': ['与源相同', '单声道', '立体声']
    }
}


def translate_format_params(format_params, list_i18n, list_org):
    for format_type, params in format_params.items():
        for param_key, param_values in params.items():
            for i, value in enumerate(param_values):
                if value in list_org:
                    index_in_org = list_org.index(value)
                    format_params[format_type][param_key][i] = list_i18n[index_in_org]
    return format_params


def get_language():
    locale = QLocale.system().name()
    if locale.startswith('zh'):
        return 'zh'  # Chinese (Simplified and Traditional)
    else:
        return 'en'  # English (default for all other languages)


def get_base_path():
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # PyInstaller
        print('at PyInstaller')
        return sys._MEIPASS
    elif hasattr(get_base_path, '__compiled__'):
        # Nuitka
        print('at Nuitka')
        return os.path.dirname(os.path.abspath(__file__))
    else:
        # dev
        print('at dev')
        return ''


def get_translator_path():
    language = get_language()

    base_path = get_base_path()

    possible_paths = [
        os.path.join(base_path, "translations", f"Navigator_Audio_Toolkit_{language}.qm"),
        os.path.join(base_path, f"Navigator_Audio_Toolkit_{language}.qm"),
    ]

    for translations_path in possible_paths:
        print(f"Attempting to load translations from: {translations_path}")
        if os.path.exists(translations_path):
            print("translations found!")
            return translations_path

    print("Failed to load translator")


def remove_screen_splash():
    if "NUITKA_ONEFILE_PARENT" in os.environ:
        splash_filename = os.path.join(
            tempfile.gettempdir(),
            "onefile_%d_splash_feedback.tmp" % int(os.environ["NUITKA_ONEFILE_PARENT"]),
        )

        if os.path.exists(splash_filename):
            os.unlink(splash_filename)


def convert_file(args):
    input_file, output_folder, ffmpeg_path, params, progress_queue = args
    output_file = os.path.join(output_folder,
                               os.path.splitext(os.path.basename(input_file))[0] + '.' + params['format'])

    command = [ffmpeg_path, '-y', '-i', input_file]
    command.extend(params['ffmpeg_params'])
    command.append(output_file)

    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        process = subprocess.Popen(command, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                                   text=True, encoding='utf-8', errors='replace', startupinfo=startupinfo)

        while True:
            line = process.stderr.readline()
            if not line:
                break
            progress_queue.put(('progress', input_file, line.strip()))

        process.wait()
        success = process.returncode == 0
        progress_queue.put(('done', input_file, success))
        return success
    except Exception as e:
        progress_queue.put(('error', input_file, str(e)))
        return False


class DragDropWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.layout = QVBoxLayout(self)
        self.text_edit = QTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setPlaceholderText(self.tr("请把要分析的媒体文件拖拽到这里..."))
        self.layout.addWidget(self.text_edit)

        self.ffprobe_layout = QHBoxLayout()
        self.ffprobe_edit = QLineEdit(self)
        self.ffprobe_edit.setText("ffprobe")
        self.ffprobe_button = QPushButton(self.tr('选择FFprobe'), self)
        self.ffprobe_button.clicked.connect(self.select_ffprobe)
        self.ffprobe_layout.addWidget(QLabel(self.tr('FFprobe路径:')))
        self.ffprobe_layout.addWidget(self.ffprobe_edit)
        self.ffprobe_layout.addWidget(self.ffprobe_button)
        self.layout.addLayout(self.ffprobe_layout)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        self.analyze_files(files)

    def validate_ffprobe(self, ffprobe_path):
        try:
            result = subprocess.run([ffprobe_path, "-version"],
                                    capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if "ffprobe version" not in result.stdout:
                raise ValueError(self.tr("所选择的不是有效的 FFprobe 可执行文件"))
            return ffprobe_path
        except subprocess.CalledProcessError:
            raise ValueError(self.tr("尝试验证FFprobe可用性时出错：\n{} \n文件可能已经损坏").format(ffprobe_path))

    def select_ffprobe(self):
        file_dialog = QFileDialog()
        ffprobe_path, _ = file_dialog.getOpenFileName(self, self.tr("选择FFprobe"), "", "FFprobe Executable (*.exe);;All Files (*)")
        if ffprobe_path:
            try:
                ffprobe_path = self.validate_ffprobe(ffprobe_path)
                self.ffprobe_edit.setText(ffprobe_path)
            except ValueError as e:
                QMessageBox.warning(self, self.tr("无效的 FFprobe"), str(e))
                return

    def analyze_files(self, files):
        info = ""
        for file in files:
            info += self.get_file_info(file) + "\n\n"
        self.text_edit.setText(info)

    def get_file_info(self, file_path):
        try:
            ffprobe_path = self.ffprobe_edit.text()
            if not ffprobe_path:
                return self.tr("请先设置FFprobe路径")

            # Get JSON format basic information
            json_cmd = [
                ffprobe_path,
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                file_path
            ]

            json_result = subprocess.run(json_cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                         creationflags=subprocess.CREATE_NO_WINDOW)

            if json_result.returncode != 0:
                raise subprocess.CalledProcessError(json_result.returncode, json_cmd, json_result.stdout,
                                                    json_result.stderr)

            info = json.loads(json_result.stdout)

            file_info = self.tr("文件: {}").format(os.path.basename(file_path)) + "\n"
            file_info += self.tr("格式: {}").format(info['format']['format_name']) + "\n"
            if 'duration' in info['format']:
                file_info += self.tr("时长: {:.2f} 秒").format(float(info['format']['duration'])) + "\n"

            total_bit_rate = int(info['format'].get('bit_rate', 0))
            if total_bit_rate > 0:
                file_info += self.tr("总码率: {} kb/s").format(total_bit_rate // 1000) + "\n"

            total_size = int(info['format'].get('size', 0))
            if total_size > 0:
                size_mb = total_size / (1024 * 1024)
                file_info += self.tr("大小: {:.1f} MiB").format(size_mb) + "\n"

            for stream in info['streams']:
                file_info += self.tr("\n流 #{}: ").format(stream['index']) + "\n"
                file_info += self.tr("类型: {}").format(stream['codec_type']) + "\n"
                file_info += self.tr("编码: {}").format(stream['codec_name']) + "\n"
                if 'width' in stream and 'height' in stream:
                    file_info += self.tr("分辨率: {}x{}").format(stream['width'], stream['height']) + "\n"
                if 'sample_rate' in stream:
                    file_info += self.tr("采样率: {} Hz").format(stream['sample_rate']) + "\n"
                if 'channels' in stream:
                    file_info += self.tr("声道: {}").format(stream['channels']) + "\n"

                stream_bit_rate = int(stream.get('bit_rate', 0))
                if stream_bit_rate == 0 and stream['codec_type'] == 'audio' and len(info['streams']) == 1:
                    stream_bit_rate = total_bit_rate
                if stream_bit_rate > 0:
                    file_info += self.tr("码率: {} kb/s").format(stream_bit_rate // 1000) + "\n"

                if stream['codec_type'] == 'audio' and len(info['streams']) == 1:
                    # For single audio stream files, assume the entire file is this stream
                    stream_size = total_size
                elif 'duration' in stream:
                    stream_size = int(float(stream['duration']) * stream_bit_rate / 8)
                else:
                    stream_size = 0

                if stream_size > 0:
                    size_mb = stream_size / (1024 * 1024)
                    percentage = (stream_size / total_size) * 100 if total_size > 0 else 0
                    file_info += self.tr("大小: {:.1f} MiB ({:.1f}%)").format(size_mb, percentage) + "\n"

            detail_cmd = [
                ffprobe_path,
                '-v', 'quiet',
                '-show_format',
                '-show_streams',
                file_path
            ]

            detail_result = subprocess.run(detail_cmd, capture_output=True, text=True, encoding='utf-8',
                                           errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)

            if detail_result.returncode != 0:
                raise subprocess.CalledProcessError(detail_result.returncode, detail_cmd, detail_result.stdout,
                                                    detail_result.stderr)

            file_info += self.tr("\n\n====详细信息====\n\n")
            file_info += detail_result.stdout

            return file_info
        except subprocess.CalledProcessError as e:
            return self.tr("无法分析 {}: FFprobe 命令执行失败\n{}").format(file_path, e.stderr)
        except json.JSONDecodeError as e:
            return self.tr("无法分析 {}: JSON 解析错误\n{}").format(file_path, str(e))
        except UnicodeDecodeError as e:
            return self.tr("无法分析 {}: 编码错误\n{}").format(file_path, str(e))
        except Exception as e:
            return self.tr("无法分析 {}: {}").format(file_path, str(e))


class DragDropLineEdit(QLineEdit):
    files_dropped = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls()]
            self.setText('⁏'.join(paths))  # Merge Paths
            self.files_dropped.emit()
        else:
            super().dropEvent(event)


class ConversionManager(QThread):
    update_overall_progress = pyqtSignal(int)
    update_current_file = pyqtSignal(str)
    update_progress = pyqtSignal(str)
    all_conversions_done = pyqtSignal()

    def __init__(self, input_files, output_folder, ffmpeg_path, params, num_processes):
        super().__init__()
        self.input_files = input_files
        self.output_folder = output_folder
        self.ffmpeg_path = ffmpeg_path
        self.params = params
        self.num_processes = num_processes
        self.is_running = False
        self.success_count = 0
        self.failed_files = []
        self.is_stopped_by_user = False
        self.progress_queue = None

    def run(self):
        self.is_running = True
        manager = Manager()
        self.progress_queue = manager.Queue()

        pool = Pool(processes=self.num_processes)
        total_files = len(self.input_files)

        args = [(input_file, self.output_folder, self.ffmpeg_path, self.params, self.progress_queue)
                for input_file in self.input_files]

        async_result = pool.map_async(convert_file, args)

        completed_count = 0
        while not async_result.ready() or not self.progress_queue.empty():
            try:
                msg_type, file, data = self.progress_queue.get(timeout=0.1)
                if msg_type == 'progress':
                    self.update_progress.emit(f"{os.path.basename(file)}: {data}")
                elif msg_type == 'done':
                    completed_count += 1
                    if data:
                        self.success_count += 1
                    else:
                        self.failed_files.append(os.path.basename(file))
                    progress = int((completed_count / total_files) * 100)
                    self.update_overall_progress.emit(progress)
                    self.update_current_file.emit(self.tr("已完成: {}").format(os.path.basename(file)))
                elif msg_type == 'error':
                    self.update_progress.emit(self.tr("错误 ({}): {}").format(os.path.basename(file), data))
            except queue.Empty:
                continue

            if not self.is_running:
                pool.terminate()
                break

        pool.close()
        pool.join()
        self.all_conversions_done.emit()

    def stop(self):
        self.is_running = False
        self.is_stopped_by_user = True


class AudioConverter(QWidget):
    def __init__(self):
        super().__init__()
        self.resampler = 'default'
        self.aac_encoder = 'aac'
        self.progress_text_edit = None
        self.convert_button = None
        self.progress_bar = None
        self.file_count_label = None
        self.ffmpeg_edit = None
        self.process_count_spinbox = None
        self.channels_combo = None
        self.bits_combo = None
        self.sample_rate_edit = None
        self.sample_rate_combo = None
        self.bitrate_edit = None
        self.bitrate_combo = None
        self.preset_combo = None
        self.format_combo = None
        self.output_edit = None
        self.input_edit = None
        self.file_info_tab = None
        self.fap_analysis_tab = None
        self.slice_audio_tab = None
        self.loudness_tab = None
        self.tab_widget = None
        self.initUI()
        self.update_params()
        self.setWindowIcon(QIcon(":/images/icon.ico"))
        self.load_presets()
        self.update_file_count()
        self.settings = QSettings('Settings.ini', QSettings.IniFormat)
        self.load_settings()
        self.conversion_manager = None
        self.is_converting = False
        self.format_combo.currentTextChanged.connect(self.update_params)
        self.setStyleSheet("""
                    QGroupBox {
                        font-weight: Normal;
                        background-color: rgba(255, 255, 255, 220);
                    }
                    QGroupBox::title {
                        subcontrol-origin: margin;
                        left: 10px;
                        padding: 0 3px 0 3px;
                    }
                    QPushButton {
                        padding: 6px;
                        border: 2px dashed #696969;
                    }
                    QTabBar::tab {
                        padding: 5px 10px;
                    }
                    QTabBar::tab:hover {
                        padding: 1px 1px;
                    }
                    QSplitter{
                    background-color: rgba(255, 255, 255, 220);
                    }
                    QTextEdit{
                    background-color: rgba(255, 255, 255, 220);
                    }
                """)
        self.check_ffmpeg()
        self.check_ffprobe()

    def initUI(self):
        # Get the primary screen scaling_factor
        screen = QApplication.primaryScreen()
        dpi = screen.logicalDotsPerInch()
        scaling_factor = max(1.0, dpi / 96.0)  # assuming 96 DPI as the base

        # Scale the window size
        base_width, base_height = 650, 450
        scaled_width = int(base_width * scaling_factor)
        scaled_height = int(base_height * scaling_factor)
        self.setWindowTitle(self.tr('未鸟的音频工具箱 v0.1.1'))
        self.setGeometry(100, 100, scaled_width, scaled_height)

        # Scale the font, in theory this is redundant but there are strange special cases
        font = QApplication.font()
        font.setPointSize(int(font.pointSize()))
        QApplication.setFont(font)

        main_layout = QVBoxLayout()

        # Create a tab
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # Main function tab
        main_tab = QWidget()
        main_tab_layout = QVBoxLayout(main_tab)
        self.tab_widget.addTab(main_tab, self.tr("音频转换"))
        self.set_tab_background(main_tab, ":/images/background.png")

        # Loudness Normalization tab
        self.loudness_tab = LoudnessNormalizationTab()
        self.tab_widget.addTab(self.loudness_tab, self.tr("响度匹配"))
        self.set_tab_background(self.loudness_tab, ":/images/background.png")

        # Slice Audio tab
        self.slice_audio_tab = SliceAudioTab()
        self.tab_widget.addTab(self.slice_audio_tab, self.tr("音频切片"))
        self.set_tab_background(self.slice_audio_tab, ":/images/background.png")

        # Data Analysis tab
        self.fap_analysis_tab = FapAnalysisTab()
        self.tab_widget.addTab(self.fap_analysis_tab, self.tr("数据分析"))
        self.set_tab_background(self.fap_analysis_tab, ":/images/background.png")

        # File Information Tab
        self.file_info_tab = DragDropWidget()
        self.tab_widget.addTab(self.file_info_tab, self.tr("文件信息"))
        self.set_tab_background(self.file_info_tab, ":/images/background.png")

        # Input and Output Settings
        io_group = QGroupBox(self.tr("输入/输出设置"))
        io_layout = QVBoxLayout()

        input_layout = QHBoxLayout()
        self.input_edit = DragDropLineEdit()
        self.input_edit.files_dropped.connect(self.update_file_count)
        input_button = QPushButton(self.tr('选择输入'))
        input_button.clicked.connect(self.select_input)
        input_layout.addWidget(QLabel(self.tr('输入:')))
        input_layout.addWidget(self.input_edit)
        input_layout.addWidget(input_button)

        output_layout = QHBoxLayout()
        self.output_edit = DragDropLineEdit()
        output_button = QPushButton(self.tr('选择输出'))
        output_button.clicked.connect(self.select_output)
        output_layout.addWidget(QLabel(self.tr('输出:')))
        output_layout.addWidget(self.output_edit)
        output_layout.addWidget(output_button)

        io_layout.addLayout(input_layout)
        io_layout.addLayout(output_layout)
        io_group.setLayout(io_layout)

        main_tab_layout.addWidget(io_group)

        # Create a horizontal splitter
        splitter = QSplitter(Qt.Horizontal)
        main_tab_layout.addWidget(splitter)

        # Left: Conversion settings
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 10, 0)  # Left, Up, Right, Down

        convert_group = QGroupBox(self.tr("转换设置"))
        convert_layout = QVBoxLayout()

        format_layout = QHBoxLayout()
        self.format_combo = QComboBox()
        self.format_combo.addItems(['mp3', 'flac', 'wav', 'aac', 'ogg', 'opus'])
        self.format_combo.currentTextChanged.connect(self.update_params)
        format_layout.addWidget(QLabel(self.tr('格式:')))
        format_layout.addWidget(self.format_combo)

        bitrate_layout = QHBoxLayout()
        self.bitrate_combo = QComboBox()
        self.bitrate_combo.addItems(['320k', '256k', '192k', '128k', self.tr('自定义')])
        self.bitrate_combo.currentTextChanged.connect(self.on_bitrate_changed)
        self.bitrate_edit = QLineEdit()
        self.bitrate_edit.setVisible(False)
        bitrate_layout.addWidget(QLabel(self.tr('码率:')))
        bitrate_layout.addWidget(self.bitrate_combo)
        bitrate_layout.addWidget(self.bitrate_edit)

        sample_rate_layout = QHBoxLayout()
        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.addItems([self.tr('与源相同'), '44100', '48000', '96000', self.tr('自定义')])
        self.sample_rate_combo.currentTextChanged.connect(self.on_sample_rate_changed)
        self.sample_rate_edit = QLineEdit()
        self.sample_rate_edit.setVisible(False)
        sample_rate_layout.addWidget(QLabel(self.tr('采样率:')))
        sample_rate_layout.addWidget(self.sample_rate_combo)
        sample_rate_layout.addWidget(self.sample_rate_edit)

        bits_layout = QHBoxLayout()
        self.bits_combo = QComboBox()
        self.bits_combo.addItems([self.tr('与源相同'), '16', '24', '32', 'float'])
        bits_layout.addWidget(QLabel(self.tr('位深度:')))
        bits_layout.addWidget(self.bits_combo)

        channels_layout = QHBoxLayout()
        self.channels_combo = QComboBox()
        self.channels_combo.addItems([self.tr('与源相同'), self.tr('单声道'), self.tr('立体声')])
        channels_layout.addWidget(QLabel(self.tr('声道:')))
        channels_layout.addWidget(self.channels_combo)

        process_layout = QHBoxLayout()
        process_layout.addWidget(QLabel(self.tr('工作进程数:')))
        self.process_count_spinbox = QSpinBox()
        self.process_count_spinbox.setRange(1, multiprocessing.cpu_count())
        self.process_count_spinbox.setValue(multiprocessing.cpu_count())
        process_layout.addWidget(self.process_count_spinbox)

        convert_layout.addLayout(format_layout)
        convert_layout.addLayout(bitrate_layout)
        convert_layout.addLayout(sample_rate_layout)
        convert_layout.addLayout(bits_layout)
        convert_layout.addLayout(channels_layout)
        convert_layout.addLayout(process_layout)

        convert_group.setLayout(convert_layout)

        left_layout.addWidget(convert_group)
        left_layout.addStretch(1)

        # Right: Presets and FFmpeg settings
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 0, 0, 0)  # Left, Up, Right, Down

        # Create a new group box for both presets and FFmpeg settings
        settings_group = QGroupBox(self.tr("基础设置"))
        settings_layout = QVBoxLayout()

        # Create labels with fixed width
        preset_label = QLabel(self.tr("预设:"))
        ffmpeg_label = QLabel(self.tr('FFmpeg路径:'))

        # Set fixed width for labels
        label_width = ffmpeg_label.sizeHint().width()
        preset_label.setFixedWidth(label_width)
        ffmpeg_label.setFixedWidth(label_width)

        # Presets
        preset_layout = QHBoxLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.currentTextChanged.connect(self.load_preset)
        save_preset_button = QPushButton(self.tr('保存预设'))
        save_preset_button.clicked.connect(self.save_preset)

        self.preset_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        save_preset_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        preset_layout.addWidget(preset_label)
        preset_layout.addWidget(self.preset_combo)
        preset_layout.addWidget(save_preset_button)
        settings_layout.addLayout(preset_layout)

        # FFmpeg settings
        ffmpeg_layout = QHBoxLayout()
        self.ffmpeg_edit = QLineEdit()
        self.ffmpeg_edit.setText("ffmpeg")
        ffmpeg_button = QPushButton(self.tr('选择FFmpeg'))
        ffmpeg_button.clicked.connect(self.select_ffmpeg)

        self.ffmpeg_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        ffmpeg_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        ffmpeg_layout.addWidget(ffmpeg_label)
        ffmpeg_layout.addWidget(self.ffmpeg_edit)
        ffmpeg_layout.addWidget(ffmpeg_button)
        settings_layout.addLayout(ffmpeg_layout)

        button_width = max(save_preset_button.sizeHint().width(), ffmpeg_button.sizeHint().width())
        save_preset_button.setFixedWidth(button_width)
        ffmpeg_button.setFixedWidth(button_width)

        settings_group.setLayout(settings_layout)
        right_layout.addWidget(settings_group)

        # File count label
        self.file_count_label = QLabel(self.tr('当前总待处理文件数: 0'))
        self.file_count_label.setAlignment(Qt.AlignLeft)
        right_layout.addWidget(self.file_count_label)

        right_layout.addStretch(1)

        # Progress Bar
        progress_bar_group = QGroupBox(self.tr("进度"))
        progress_bar_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        progress_bar_group.setLayout(progress_bar_layout)
        progress_bar_layout.addWidget(self.progress_bar)
        right_layout.addWidget(progress_bar_group)

        # Add left and right widget to the splitter
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)

        # Convert button and Open output folder button
        button_layout = QHBoxLayout()
        self.convert_button = QPushButton(self.tr('开始转换'))
        self.convert_button.clicked.connect(self.toggle_conversion)
        open_output_button = QPushButton(self.tr('打开输出文件夹'))
        open_output_button.clicked.connect(self.open_output_folder)
        button_layout.addWidget(self.convert_button)
        button_layout.addWidget(open_output_button)
        main_tab_layout.addLayout(button_layout)

        # Progress text box
        self.progress_text_edit = QTextEdit()
        self.progress_text_edit.setReadOnly(True)
        self.progress_text_edit.setPlaceholderText(
            self.tr("GitHub开源地址：https://github.com/AliceNavigator/Navigator-Audio-Toolkit\n\n"
                    "改后缀并不是转格式，请告诉每一个试图这么干的人并把这个软件塞给他！\n\n"
                    "                                               by  领航员未鸟"))
        main_tab_layout.addWidget(self.progress_text_edit)

        self.setLayout(main_layout)

    def toggle_conversion(self):
        if not self.is_converting:
            self.start_conversion()
        else:
            self.stop_conversion()

    def copy_progress(self):
        selected_items = self.progress_list.selectedItems()
        if selected_items:
            clipboard = QApplication.clipboard()
            text = "\n".join([item.text() for item in selected_items])
            clipboard.setText(text)

    def open_output_folder(self):
        output_folder = self.output_edit.text()
        if os.path.isdir(output_folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(output_folder))
        else:
            QMessageBox.warning(self, self.tr('警告'), self.tr('输出文件夹无效'))

    def closeEvent(self, event):
        if self.conversion_manager and self.conversion_manager.isRunning():
            self.conversion_manager.stop()
            self.conversion_manager.wait()
        self.save_settings()
        event.accept()

    def check_ffmpeg(self):
        # Check the path in the edit box first
        ffmpeg_path = self.ffmpeg_edit.text()
        if ffmpeg_path and self.is_valid_ffmpeg(ffmpeg_path):
            self.update_ffmpeg_capabilities(ffmpeg_path)
            return

        # Then check in the system PATH
        ffmpeg_path = shutil.which('ffmpeg')
        if ffmpeg_path:
            self.ffmpeg_edit.setText(ffmpeg_path)
            self.update_ffmpeg_capabilities(ffmpeg_path)
            return

        # If we get here, no valid FFprobe was found
        QMessageBox.warning(self, self.tr('警告'),
                            self.tr('FFmpeg未在系统PATH或指定路径中找到，请手动指定正确的FFmpeg路径'))

    def is_valid_ffmpeg(self, path):
        try:
            result = subprocess.run([path, '-version'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    creationflags=subprocess.CREATE_NO_WINDOW, text=True, encoding='utf-8',
                                    errors='replace')
            return "ffmpeg version" in result.stdout
        except (FileNotFoundError, subprocess.CalledProcessError):
            return False

    def update_ffmpeg_capabilities(self, ffmpeg_path):
        result = subprocess.run([ffmpeg_path, '-version'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=subprocess.CREATE_NO_WINDOW, text=True, encoding='utf-8',
                                errors='replace')

        if '--enable-libsoxr' in result.stdout:
            self.resampler = 'soxr'
        else:
            self.resampler = 'default'

        if '--enable-libfdk-aac' in result.stdout:
            # libfdk_aac cuts off the spectrum at around 17kHz, which I don't like. It can be enabled if necessary, but for now, the built-in encoder performs better.
            self.aac_encoder = 'aac'
            # self.aac_encoder = 'libfdk_aac'
        else:
            self.aac_encoder = 'aac'

    def check_ffprobe(self):
        # Check the path in the edit box first
        ffprobe_path = self.file_info_tab.ffprobe_edit.text()
        if ffprobe_path and self.is_valid_ffprobe(ffprobe_path):
            return

        # Then check in the system PATH
        ffprobe_path = shutil.which('ffprobe')
        if ffprobe_path:
            self.file_info_tab.ffprobe_edit.setText(ffprobe_path)
            return

        # If we get here, no valid FFprobe was found
        QMessageBox.warning(self, self.tr('警告'),
                            self.tr('FFprobe未在系统PATH或指定路径中找到，请手动指定正确的FFprobe路径'))

    def is_valid_ffprobe(self, path):
        try:
            result = subprocess.run([path, '-version'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    creationflags=subprocess.CREATE_NO_WINDOW, text=True, encoding='utf-8',
                                    errors='replace')
            return "ffprobe version" in result.stdout
        except (FileNotFoundError, subprocess.CalledProcessError):
            return False

    def select_input(self):
        file_dialog = QFileDialog()
        file_dialog.setFileMode(QFileDialog.ExistingFiles)
        if file_dialog.exec_():
            files = file_dialog.selectedFiles()
            self.input_edit.setText('⁏'.join(files))
            self.update_file_count()

    def update_file_count(self):
        file_count = len(self.input_edit.text().split('⁏')) if self.input_edit.text() else 0
        self.file_count_label.setText(self.tr('当前总待处理文件数: {}').format(file_count))

    def select_output(self):
        folder = QFileDialog.getExistingDirectory(self, self.tr('选择输出文件夹'))
        if folder:
            self.output_edit.setText(folder)

    def validate_ffmpeg(self, ffmpeg_path):
        try:
            result = subprocess.run([ffmpeg_path, "-version"],
                                    capture_output=True, text=True, check=True,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            if "ffmpeg version" not in result.stdout:
                raise ValueError(self.tr("所选择的不是有效的 FFmpeg 可执行文件"))
            return ffmpeg_path
        except subprocess.CalledProcessError:
            raise ValueError(self.tr("尝试验证FFmpeg可用性时出错：\n{} \n文件可能已经损坏").format(ffmpeg_path))

    def select_ffmpeg(self):
        file_dialog = QFileDialog()
        ffmpeg_path, _ = file_dialog.getOpenFileName(self, self.tr("选择FFmpeg"), "",
                                                     "FFmpeg Executable (*.exe);;All Files (*)")
        if ffmpeg_path:
            try:
                ffmpeg_path = self.validate_ffmpeg(ffmpeg_path)
                self.ffmpeg_edit.setText(ffmpeg_path)
            except ValueError as e:
                QMessageBox.warning(self, self.tr("无效的 FFmpeg"), str(e))
                return

    def update_params(self):
        list_i18n = [self.tr("与源相同"), self.tr("单声道"), self.tr("立体声"), self.tr("自定义")]
        list_org = ['与源相同', '单声道', '立体声', '自定义']
        translated_params = translate_format_params(FORMAT_PARAMS, list_i18n, list_org)

        current_format = self.format_combo.currentText()
        params = translated_params.get(current_format, {})

        self.bitrate_combo.clear()
        self.bitrate_combo.addItems(params.get('bitrate', [self.tr('与源相同')]))
        self.bitrate_combo.setEnabled(len(params.get('bitrate', [])) > 1)
        self.bitrate_edit.setVisible(False)

        self.sample_rate_combo.clear()
        self.sample_rate_combo.addItems(params.get('sample_rate', [self.tr('与源相同')]))
        self.sample_rate_combo.setEnabled(len(params.get('sample_rate', [])) > 1)
        self.sample_rate_edit.setVisible(False)

        self.bits_combo.clear()
        self.bits_combo.addItems(params.get('bits', [self.tr('与源相同')]))
        self.bits_combo.setEnabled(len(params.get('bits', [])) > 1)

        self.channels_combo.clear()
        self.channels_combo.addItems(params.get('channels', [self.tr('与源相同')]))
        self.channels_combo.setEnabled(len(params.get('channels', [])) > 1)

        self.reset_disabled_options()

        self.on_bitrate_changed(self.bitrate_combo.currentText())
        self.on_sample_rate_changed(self.sample_rate_combo.currentText())

    def reset_disabled_options(self):
        if not self.bitrate_combo.isEnabled():
            self.bitrate_combo.setCurrentText(self.tr('与源相同'))
        if not self.bits_combo.isEnabled():
            self.bits_combo.setCurrentText(self.tr('与源相同'))

    def on_bitrate_changed(self, text):
        self.bitrate_edit.setVisible(text == self.tr('自定义'))

    def on_sample_rate_changed(self, text):
        self.sample_rate_edit.setVisible(text == self.tr('自定义'))

    def save_preset(self):
        preset_name, ok = QInputDialog.getText(self, self.tr('保存预设'), self.tr('输入预设名称:'))
        if ok and preset_name:
            preset = {
                'format': self.format_combo.currentText(),
                'bitrate': self.bitrate_combo.currentText(),
                'sample_rate': self.sample_rate_combo.currentText(),
                'bits': self.bits_combo.currentText(),
                'channels': self.channels_combo.currentText()
            }
            if not hasattr(self, 'presets'):
                self.presets = {}
            self.presets[preset_name] = preset
            self.save_presets()
            self.preset_combo.addItem(preset_name)

    def load_preset(self, preset_name):
        if hasattr(self, 'presets') and preset_name in self.presets:
            preset = self.presets[preset_name]
            self.format_combo.setCurrentText(preset['format'])
            self.bitrate_combo.setCurrentText(preset['bitrate'])
            self.sample_rate_combo.setCurrentText(preset['sample_rate'])
            self.bits_combo.setCurrentText(preset['bits'])
            self.channels_combo.setCurrentText(preset['channels'])

            self.on_bitrate_changed(preset['bitrate'])
            self.on_sample_rate_changed(preset['sample_rate'])

    def save_presets(self):
        with open('presets.json', 'w') as f:
            json.dump(self.presets, f, indent=4)

    def load_presets(self):
        try:
            with open('presets.json', 'r') as f:
                self.presets = json.load(f)
            self.preset_combo.addItems(self.presets.keys())
        except FileNotFoundError:
            self.presets = {}

    def get_input_audio_channels(self, input_file):
        ffprobe_path = self.file_info_tab.ffprobe_edit.text()
        cmd = [
            ffprobe_path,
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_streams',
            '-select_streams', 'a:0',
            input_file
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            data = json.loads(result.stdout)
            return int(data['streams'][0]['channels'])
        except Exception as e:
            print(f"Error getting audio channels: {e}")
            return None

    def validate_params(self, params, input_files):
        format = params['format']
        ffmpeg_params = params['ffmpeg_params']

        # Extract parameters
        bitrate = next((p for i, p in enumerate(ffmpeg_params) if ffmpeg_params[i - 1] == '-b:a'), None)
        channels = next((p for i, p in enumerate(ffmpeg_params) if ffmpeg_params[i - 1] == '-ac'), None)
        sample_rate = next((p for i, p in enumerate(ffmpeg_params) if ffmpeg_params[i - 1] == '-ar'), None)
        bits = next((p for i, p in enumerate(ffmpeg_params) if ffmpeg_params[i - 1] == '-sample_fmt'), None)

        # Check mono setting
        is_mono_setting = channels == '1' or self.channels_combo.currentText() == self.tr('单声道')
        is_source_setting = self.channels_combo.currentText() == self.tr('与源相同')

        # Define format-specific constraints
        format_constraints = {
            'opus': {'max_bitrate_mono': 256},
            'ogg': {'max_bitrate_mono': 192}
        }

        for input_file in input_files:
            input_channels = self.get_input_audio_channels(input_file)

            if input_channels is None:
                self.progress_text_edit.append(self.tr('警告：无法获取输入文件的声道信息: {}\n将跳过此文件的声道相关检查。').format(input_file))
                continue  # Skip channel-related checks for this file

            is_mono = is_mono_setting or (is_source_setting and input_channels == 1)

            if format in format_constraints:
                constraints = format_constraints[format]
                if is_mono and bitrate:
                    max_bitrate = constraints['max_bitrate_mono']
                    current_bitrate = int(bitrate.replace('k', ''))
                    if current_bitrate > max_bitrate:
                        QMessageBox.warning(self, self.tr('参数错误'),
                                            self.tr('{} 格式在单声道模式下的最大码率为 {}k').format(format, max_bitrate))
                        return False

        # Additional parameter checks can be added here

        return True

    def is_valid_output_folder(self, folder_path):
        if not folder_path:
            return False
        if not os.path.exists(folder_path):
            try:
                os.makedirs(folder_path)
            except OSError:
                return False
        return os.path.isdir(folder_path) and os.access(folder_path, os.W_OK)

    def start_conversion(self):
        self.progress_text_edit.clear()
        input_paths = self.input_edit.text().split('⁏')
        output_folder = self.output_edit.text()
        ffmpeg_path = self.ffmpeg_edit.text()

        if not input_paths or not output_folder or not ffmpeg_path:
            QMessageBox.warning(self, self.tr('警告'), self.tr('请填写所有必要信息'))
            return

        if not self.is_valid_output_folder(output_folder):
            QMessageBox.warning(self, self.tr('警告'), self.tr('输出文件夹路径无效或无写入权限'))
            return

        input_files = input_paths

        params = {
            'format': self.format_combo.currentText(),
            'ffmpeg_params': []
        }

        params.update(self.get_audio_params())

        '''
        if not self.validate_params(params, input_paths):
            return
        '''

        self.is_converting = True
        self.convert_button.setText(self.tr('强制终止'))
        self.convert_button.setStyleSheet("background-color: red; color: white;")

        num_processes = self.process_count_spinbox.value()

        if self.conversion_manager and self.conversion_manager.isRunning():
            self.conversion_manager.stop()
            self.conversion_manager.wait()

        self.conversion_manager = ConversionManager(input_files, output_folder, ffmpeg_path, params, num_processes)
        self.conversion_manager.update_overall_progress.connect(self.update_overall_progress)
        self.conversion_manager.update_current_file.connect(self.update_current_file)
        self.conversion_manager.update_progress.connect(self.update_progress)
        self.conversion_manager.all_conversions_done.connect(self.all_conversions_done)
        self.conversion_manager.start()

    def get_audio_params(self):
        format_handlers = {
            'mp3': self.handle_mp3,
            'flac': self.handle_flac,
            'wav': self.handle_wav,
            'aac': self.handle_aac,
            'ogg': self.handle_ogg,
            'opus': self.handle_opus
        }

        current_format = self.format_combo.currentText()
        handler = format_handlers.get(current_format, self.handle_default)
        return handler()

    def handle_default(self):
        params = []
        # Ignore the video stream
        params.extend(['-vn'])

        if self.bitrate_combo.currentText() == self.tr('自定义'):
            bitrate = self.bitrate_edit.text()
            if not bitrate.endswith('k'):
                bitrate += 'k'
            params.extend(['-b:a', bitrate])
        elif self.bitrate_combo.currentText() != self.tr('与源相同'):
            params.extend(['-b:a', self.bitrate_combo.currentText()])

        if self.sample_rate_combo.currentText() == self.tr('自定义') or self.sample_rate_combo.currentText() != self.tr(
                '与源相同'):
            if self.resampler == 'soxr':
                params.extend(['-af', f'aresample=resampler=soxr'])
            else:
                params.extend(['-af', f'aresample'])

        if self.sample_rate_combo.currentText() == self.tr('自定义'):
            sample_rate = self.sample_rate_edit.text()
            params.extend(['-ar', sample_rate])
        elif self.sample_rate_combo.currentText() != self.tr('与源相同'):
            params.extend(['-ar', self.sample_rate_combo.currentText()])

        if self.bits_combo.currentText() != self.tr('与源相同'):
            if self.bits_combo.currentText() == 'float':
                params.extend(['-acodec', 'pcm_f32le'])
            elif self.bits_combo.currentText() == '32':
                params.extend(['-acodec', 'pcm_s32le'])
            elif self.bits_combo.currentText() == '24':
                params.extend(['-acodec', 'pcm_s24le'])
            elif self.bits_combo.currentText() == '16':
                params.extend(['-acodec', 'pcm_s16le'])

        if self.channels_combo.currentText() == self.tr('单声道'):
            params.extend(['-ac', '1'])
        elif self.channels_combo.currentText() == self.tr('立体声'):
            params.extend(['-ac', '2'])

        return {'ffmpeg_params': params}

    def handle_mp3(self):
        params = self.handle_default()
        params['ffmpeg_params'].extend(['-acodec', 'libmp3lame'])
        return params

    def handle_flac(self):
        params = []
        # Ignore the video stream
        params.extend(['-vn'])
        params.extend(['-c:a', 'flac'])

        compression_level = '5'
        params.extend(['-compression_level', compression_level])

        if self.sample_rate_combo.currentText() == self.tr('自定义') or self.sample_rate_combo.currentText() != self.tr(
                '与源相同'):
            if self.resampler == 'soxr':
                params.extend(['-af', f'aresample=resampler=soxr'])
            else:
                params.extend(['-af', f'aresample'])

        if self.sample_rate_combo.currentText() == self.tr('自定义'):
            sample_rate = self.sample_rate_edit.text()
            params.extend(['-ar', sample_rate])
        elif self.sample_rate_combo.currentText() != self.tr('与源相同'):
            params.extend(['-ar', self.sample_rate_combo.currentText()])

        if self.bits_combo.currentText() != self.tr('与源相同'):
            bit_depth = self.bits_combo.currentText()
            if bit_depth == '16':
                params.extend(['-sample_fmt', 's16'])
            elif bit_depth == '24':
                params.extend(['-sample_fmt', 's32', '-bits_per_raw_sample', '24'])

        if self.channels_combo.currentText() == self.tr('单声道'):
            params.extend(['-ac', '1'])
        elif self.channels_combo.currentText() == self.tr('立体声'):
            params.extend(['-ac', '2'])

        return {'ffmpeg_params': params}

    def handle_wav(self):
        params = self.handle_default()
        params['ffmpeg_params'].extend(['-f', 'wav'])
        return params

    def handle_aac(self):
        params = self.handle_default()
        params['ffmpeg_params'].extend(['-c:a', self.aac_encoder])
        return params

    def handle_ogg(self):
        params = self.handle_default()
        params['ffmpeg_params'].extend(['-c:a', 'libvorbis'])
        return params

    def handle_opus(self):
        params = self.handle_default()
        params['ffmpeg_params'].extend(['-c:a', 'libopus'])
        return params

    def stop_conversion(self):
        if self.conversion_manager and self.conversion_manager.isRunning():
            self.conversion_manager.stop()
            self.conversion_manager.wait()

        self.is_converting = False
        self.convert_button.setText(self.tr('开始转换'))
        self.convert_button.setStyleSheet("")
        self.progress_text_edit.append(self.tr("转换已终止"))

        QMessageBox.information(self, self.tr('转换终止'), self.tr('转换已由用户强制终止'))

    def update_progress(self, message):
        try:
            decoded_message = message.encode('utf-8', 'ignore').decode('utf-8')
            self.progress_text_edit.append(decoded_message)
            self.progress_text_edit.moveCursor(QTextCursor.End)
        except Exception as e:
            print(f"Error updating progress: {str(e)}")

    def update_overall_progress(self, progress):
        self.progress_bar.setValue(progress)

    def update_current_file(self, message):
        self.progress_text_edit.append(message)
        self.progress_text_edit.moveCursor(QTextCursor.End)

    def all_conversions_done(self):
        total_files = len(self.conversion_manager.input_files)
        success_count = self.conversion_manager.success_count
        failed_count = len(self.conversion_manager.failed_files)

        message = self.tr("总计处理{}个文件，成功{}个，失败{}个").format(total_files, success_count, failed_count)

        if failed_count > 0 and not self.conversion_manager.is_stopped_by_user:
            failed_files_text = "\n".join(self.conversion_manager.failed_files)

            custom_dialog = QDialog(self)
            custom_dialog.setWindowTitle(self.tr("转换完成"))
            custom_dialog.setMinimumWidth(400)
            custom_dialog.setMinimumHeight(300)

            layout = QVBoxLayout()

            top_layout = QHBoxLayout()

            icon_label = QLabel()
            icon_label.setPixmap(self.style().standardIcon(QStyle.SP_MessageBoxWarning).pixmap(32, 32))
            top_layout.addWidget(icon_label)

            right_layout = QVBoxLayout()

            message_label = QLabel(message)
            right_layout.addWidget(message_label)

            info_label = QLabel(self.tr("以下是转换失败的文件："))
            right_layout.addWidget(info_label)

            top_layout.addLayout(right_layout)
            top_layout.addStretch(1)

            layout.addLayout(top_layout)

            failed_files_text_edit = QTextEdit()
            failed_files_text_edit.setPlainText(failed_files_text)
            failed_files_text_edit.append(
                self.tr("\n\n以下是一些常见失败原因：\n\n"
                        "1.转为ogg格式时：\n  原始文件采样率非44.1或者48kHz，而选择了与源相同，或者自定义码率超过500k。单声道文件码率超过192k\n\n"
                        "2.转为opus格式时：\n  单声道文件码率超过256k，无论是手动设置还是尝试转换单声道文件\n\n"
                        "3.转为aac格式时：\n  原始文件采样率非支持的数值（见下拉菜单），而选择了与源相同\n\n"
                        "4.转为flac格式时：\n  在自定义数值上设置了常规播放器不支持的数值，虽然可以转换，但可能只有专业软件能打开\n\n"
                        "5.其他：\n  请检查你的输入文件，它可能已损坏或被加密，如果是Unicode编码问题一般可以通过简单的改名解决\n\n"
                        "此外，请妥善利用文件信息页面，通过把媒体文件拖入能得到详细的信息帮助你确定错误。\n\n")
            )
            failed_files_text_edit.setReadOnly(True)
            layout.addWidget(failed_files_text_edit)

            ok_button = QPushButton(self.tr("确定"))
            ok_button.clicked.connect(custom_dialog.accept)
            layout.addWidget(ok_button)

            custom_dialog.setLayout(layout)
            custom_dialog.exec_()
        elif not self.conversion_manager.is_stopped_by_user:
            QMessageBox.information(self, self.tr('转换完成'), message)

        self.progress_bar.setValue(0)
        self.is_converting = False
        self.convert_button.setText(self.tr('开始转换'))
        self.convert_button.setStyleSheet("")

    def save_settings(self):
        self.settings.setValue("input_path", self.input_edit.text())
        self.settings.setValue("output_path", self.output_edit.text())
        self.settings.setValue("ffmpeg_path", self.ffmpeg_edit.text())
        self.settings.setValue("ffprobe_path", self.file_info_tab.ffprobe_edit.text())

        self.settings.setValue("format", self.format_combo.currentText())
        self.settings.setValue("bitrate", self.bitrate_combo.currentText())
        self.settings.setValue("custom_bitrate", self.bitrate_edit.text())
        self.settings.setValue("sample_rate", self.sample_rate_combo.currentText())
        self.settings.setValue("custom_sample_rate", self.sample_rate_edit.text())
        self.settings.setValue("bits", self.bits_combo.currentText())
        self.settings.setValue("channels", self.channels_combo.currentText())
        self.settings.setValue("process_count", self.process_count_spinbox.value())

    def load_settings(self):
        self.input_edit.setText(self.settings.value("input_path", ""))
        self.output_edit.setText(self.settings.value("output_path", ""))
        ffmpeg_path = self.settings.value("ffmpeg_path", "")
        ffprobe_path = self.settings.value("ffprobe_path", "")

        if ffmpeg_path:
            self.ffmpeg_edit.setText(ffmpeg_path)
        else:
            self.ffmpeg_edit.setText('ffmpeg')

        if ffprobe_path:
            self.file_info_tab.ffprobe_edit.setText(ffprobe_path)
        else:
            self.file_info_tab.ffprobe_edit.setText('ffprobe')

        format = self.settings.value("format", "mp3")
        self.format_combo.setCurrentText(format)
        self.update_params()

        self.bitrate_combo.setCurrentText(self.settings.value("bitrate", "320k"))
        self.bitrate_edit.setText(self.settings.value("custom_bitrate", ""))
        self.sample_rate_combo.setCurrentText(self.settings.value("sample_rate", self.tr('与源相同')))
        self.sample_rate_edit.setText(self.settings.value("custom_sample_rate", ""))
        self.bits_combo.setCurrentText(self.settings.value("bits", self.tr('与源相同')))
        self.channels_combo.setCurrentText(self.settings.value("channels", self.tr('与源相同')))

        self.on_bitrate_changed(self.bitrate_combo.currentText())
        self.on_sample_rate_changed(self.sample_rate_combo.currentText())
        process_count = self.settings.value("process_count", multiprocessing.cpu_count(), type=int)
        self.process_count_spinbox.setValue(process_count)
        self.update_file_count()

    def set_tab_background(self, tab_widget, image_path):
        background = QPixmap(image_path)
        if background.isNull():
            print(f"Failed to load background image: {image_path}")
            return

        overlay = QPixmap(background.size())
        overlay.fill(QColor(255, 255, 255, 128))

        painter = QPainter(background)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.drawPixmap(0, 0, overlay)
        painter.end()

        background_label = QLabel(tab_widget)
        background_label.setPixmap(background)
        background_label.setScaledContents(True)
        background_label.resize(tab_widget.size())
        background_label.lower()

        background_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        background_label.setStyleSheet("background-color: transparent;")

        background_label.lower()

        def update_background_size(event):
            background_label.resize(event.size())
            QWidget.resizeEvent(tab_widget, event)

        tab_widget.resizeEvent = update_background_size

        for child in tab_widget.children():
            if isinstance(child, QWidget) and child is not background_label:
                child.raise_()


if __name__ == '__main__':
    app = QApplication(sys.argv)

    translator = QTranslator()
    if translator.load(get_translator_path()):
        app.installTranslator(translator)
    else:
        print('Use default')

    ex = AudioConverter()
    app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyqt5', palette=LightPalette))
    remove_screen_splash()
    ex.show()
    sys.exit(app.exec_())
