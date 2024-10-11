import os
import subprocess
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                             QLabel, QLineEdit, QPushButton, QCheckBox, 
                             QSpinBox, QDoubleSpinBox, QTextEdit, QFileDialog, QMessageBox)
from PyQt5.QtCore import QThread, pyqtSignal, QSettings


def check_file_formats(input_dir, recursive=False):
    supported_formats = {'.mp3', '.flac', '.wav'}
    unsupported_files = []

    for root, _, files in os.walk(input_dir):
        for file in files:
            if file.lower() == 'desktop.ini':
                continue
            _, ext = os.path.splitext(file.lower())
            if ext and ext not in supported_formats:
                unsupported_files.append(file)
        if not recursive:
            break

    return unsupported_files


class LoudnessNormalizationWorker(QThread):
    finished = pyqtSignal()
    progress = pyqtSignal(str)
    format_check = pyqtSignal(list)

    def __init__(self, input_dir, output_dir, options):
        super().__init__()
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.options = options
        self.force_process = False

    def run(self):
        unsupported_files = check_file_formats(self.input_dir, self.options['recursive'])
        if unsupported_files:
            self.format_check.emit(unsupported_files)
            while not self.force_process:
                self.msleep(100)  # Wait for user response
            if not self.force_process:
                self.finished.emit()
                return

        cmd = ["fap", "loudness-norm"]
        for key, value in self.options.items():
            if isinstance(value, bool):
                cmd.append(f"--{key}" if value else f"--no-{key}")
            else:
                cmd.extend([f"--{key}", str(value)])
        cmd.extend([self.input_dir, self.output_dir])

        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, startupinfo=startupinfo)

        for line in process.stdout:
            self.progress.emit(line.strip())

        process.wait()
        self.finished.emit()

    def set_force_process(self, force):
        self.force_process = force


class LoudnessNormalizationTab(QWidget):
    def __init__(self):
        super().__init__()
        self.progress_text = None
        self.start_button = None
        self.block_size_sb = None
        self.workers_sb = None
        self.loudness_sb = None
        self.peak_sb = None
        self.clean_cb = None
        self.overwrite_cb = None
        self.recursive_cb = None
        self.explanation_text = None
        self.output_edit = None
        self.input_edit = None
        self.initUI()
        self.settings = QSettings('Settings.ini', QSettings.IniFormat)
        self.load_settings()

    def initUI(self):
        layout = QVBoxLayout()

        # Input/Output settings
        io_group = QGroupBox(self.tr("输入/输出设置"))
        io_layout = QVBoxLayout()
        input_layout = QHBoxLayout()
        self.input_edit = QLineEdit()
        input_button = QPushButton(self.tr('选择输入目录'))
        input_button.clicked.connect(self.select_input_dir)
        input_layout.addWidget(QLabel(self.tr('输入目录:')))
        input_layout.addWidget(self.input_edit)
        input_layout.addWidget(input_button)
        input_layout.addWidget(QPushButton(self.tr("打开"), clicked=lambda: self.open_directory(self.input_edit)))
        output_layout = QHBoxLayout()
        self.output_edit = QLineEdit()
        output_button = QPushButton(self.tr('选择输出目录'))
        output_button.clicked.connect(self.select_output_dir)
        output_layout.addWidget(QLabel(self.tr('输出目录:')))
        output_layout.addWidget(self.output_edit)
        output_layout.addWidget(output_button)
        output_layout.addWidget(QPushButton(self.tr("打开"), clicked=lambda: self.open_directory(self.output_edit)))
        io_layout.addLayout(input_layout)
        io_layout.addLayout(output_layout)
        io_group.setLayout(io_layout)
        layout.addWidget(io_group)

        # Options and Explanation
        options_group = QGroupBox(self.tr("选项"))
        options_layout = QHBoxLayout()

        # Left side: Explanation
        self.explanation_text = QTextEdit()
        self.explanation_text.setReadOnly(True)
        self.explanation_text.setPlainText(self.tr(
            "选项说明：\n\n"
            "递归搜索：在输入目录的子目录中也查找音频文件\n\n"
            "覆盖现有文件：如果输出目录中存在同名文件，则覆盖\n\n"
            "处理前清理输出目录：在开始处理前清空输出目录\n\n"
            "峰值归一化：将音频的峰值电平调整到指定的分贝值\n\n"
            "响度归一化：将音频的响度调整到指定的LUFS值\n\n"
            "测量块大小：用于响度测量的时间块大小\n\n"
            "工作进程数：同时处理的文件数量，不建议高于CPU核心数")
        )
        options_layout.addWidget(self.explanation_text, 1)

        # Right side: Options
        right_options_layout = QVBoxLayout()
        self.recursive_cb = QCheckBox(self.tr("递归搜索"))
        self.overwrite_cb = QCheckBox(self.tr("覆盖现有文件"))
        self.clean_cb = QCheckBox(self.tr("处理前清理输出目录"))
        right_options_layout.addWidget(self.recursive_cb)
        right_options_layout.addWidget(self.overwrite_cb)
        right_options_layout.addWidget(self.clean_cb)

        peak_layout = QHBoxLayout()
        peak_layout.addWidget(QLabel(self.tr("峰值归一化 (dB):")))
        self.peak_sb = QDoubleSpinBox()
        self.peak_sb.setRange(-100, 0)
        self.peak_sb.setValue(-1.0)
        peak_layout.addWidget(self.peak_sb)

        loudness_layout = QHBoxLayout()
        loudness_layout.addWidget(QLabel(self.tr("响度归一化 (LUFS):")))
        self.loudness_sb = QDoubleSpinBox()
        self.loudness_sb.setRange(-100, 0)
        self.loudness_sb.setValue(-23.0)
        loudness_layout.addWidget(self.loudness_sb)

        block_size_layout = QHBoxLayout()
        block_size_layout.addWidget(QLabel(self.tr("测量块大小 (秒):")))
        self.block_size_sb = QDoubleSpinBox()
        self.block_size_sb.setRange(0.1, 10)
        self.block_size_sb.setValue(0.4)
        block_size_layout.addWidget(self.block_size_sb)

        workers_layout = QHBoxLayout()
        workers_layout.addWidget(QLabel(self.tr("工作进程数:")))
        self.workers_sb = QSpinBox()
        self.workers_sb.setRange(1, 32)
        self.workers_sb.setValue(4)
        workers_layout.addWidget(self.workers_sb)

        right_options_layout.addLayout(peak_layout)
        right_options_layout.addLayout(loudness_layout)
        right_options_layout.addLayout(block_size_layout)
        right_options_layout.addLayout(workers_layout)

        options_layout.addLayout(right_options_layout, 1)
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)

        # Start button
        self.start_button = QPushButton(self.tr("开始处理"))
        self.start_button.clicked.connect(self.start_processing)
        layout.addWidget(self.start_button)

        # Progress display
        self.progress_text = QTextEdit()
        self.progress_text.setReadOnly(True)
        layout.addWidget(self.progress_text)

        self.setLayout(layout)

    def select_input_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, self.tr("选择输入目录"))
        if dir_path:
            self.input_edit.setText(dir_path)
            self.save_settings()

    def select_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, self.tr("选择输出目录"))
        if dir_path:
            self.output_edit.setText(dir_path)
            self.save_settings()

    def start_processing(self):
        input_dir = self.input_edit.text()
        output_dir = self.output_edit.text()

        if not input_dir or not output_dir:
            self.progress_text.append(self.tr("错误：请选择输入和输出目录"))
            return

        options = {
            "recursive": self.recursive_cb.isChecked(),
            "overwrite": self.overwrite_cb.isChecked(),
            "clean": self.clean_cb.isChecked(),
            "peak": self.peak_sb.value(),
            "loudness": self.loudness_sb.value(),
            "block-size": self.block_size_sb.value(),
            "num-workers": self.workers_sb.value()
        }

        self.worker = LoudnessNormalizationWorker(input_dir, output_dir, options)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.processing_finished)
        self.worker.format_check.connect(self.handle_unsupported_formats)

        self.start_button.setEnabled(False)
        self.progress_text.clear()
        self.progress_text.append(self.tr("开始处理..."))
        self.worker.start()

    def handle_unsupported_formats(self, unsupported_files):
        message = self.tr("以下文件格式不受支持（目前仅支持.mp3 .wav .flac）：\n\n")
        message += "\n".join(unsupported_files[:10])
        if len(unsupported_files) > 10:
            message += self.tr("共 {} 个不支持的文件").format(len(unsupported_files))

        message += self.tr("\n\n继续处理将很可能报错，是否仍要继续？")

        reply = QMessageBox.question(self, self.tr('不支持的文件格式'), message,
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            self.worker.set_force_process(True)
        else:
            self.worker.set_force_process(False)
            self.start_button.setEnabled(True)
            self.progress_text.append(self.tr("处理已取消"))

    def update_progress(self, message):
        self.progress_text.append(message)

    def processing_finished(self):
        self.progress_text.append(self.tr("处理完成"))
        self.start_button.setEnabled(True)

    def save_settings(self):
        self.settings.setValue("loudness_normalization_input_path", self.input_edit.text())
        self.settings.setValue("loudness_normalization_output_path", self.output_edit.text())

    def load_settings(self):
        self.input_edit.setText(self.settings.value("loudness_normalization_input_path", ""))
        self.output_edit.setText(self.settings.value("loudness_normalization_output_path", ""))

    def open_directory(self, line_edit):
        directory = line_edit.text()
        if directory and os.path.isdir(directory):
            os.startfile(directory)
        else:
            QMessageBox.warning(self, self.tr("错误"), self.tr("无效的目录路径"))
