import os
import sys
import re
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QCheckBox, QSpinBox, QDoubleSpinBox,
                             QTextEdit, QMessageBox, QGridLayout, QGroupBox, QFileDialog)
from PyQt5.QtCore import QThread, pyqtSignal, QSettings, QProcess
import subprocess


class SliceAudioWorker(QThread):
    finished = pyqtSignal(str)

    def __init__(self, command):
        super().__init__()
        self.command = command

    def run(self):
        try:
            result = subprocess.run(self.command, capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            self.finished.emit(result.stdout)
        except subprocess.CalledProcessError as e:
            self.finished.emit(f"Error: {e.stderr}")


class SliceAudioTab(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.settings = QSettings('Settings.ini', QSettings.IniFormat)
        self.load_settings()
        self.process = None

    def initUI(self):
        layout = QVBoxLayout()

        # Input directory selection
        input_layout = QHBoxLayout()
        self.input_dir = QLineEdit()
        input_layout.addWidget(QLabel(self.tr("输入:")))
        input_layout.addWidget(self.input_dir)
        input_layout.addWidget(QPushButton(self.tr("选择输入目录"), clicked=lambda: self.browse_directory(self.input_dir)))
        input_layout.addWidget(QPushButton(self.tr("打开"), clicked=lambda: self.open_directory(self.input_dir)))
        layout.addLayout(input_layout)

        # Output directory selection
        output_layout = QHBoxLayout()
        self.output_dir = QLineEdit()
        output_layout.addWidget(QLabel(self.tr("输出:")))
        output_layout.addWidget(self.output_dir)
        output_layout.addWidget(QPushButton(self.tr("选择输出目录"), clicked=lambda: self.browse_directory(self.output_dir)))
        output_layout.addWidget(QPushButton(self.tr("打开"), clicked=lambda: self.open_directory(self.output_dir)))
        layout.addLayout(output_layout)

        # Options
        options_group = QGroupBox(self.tr("选项"))
        options_layout = QVBoxLayout()

        # Checkboxes in one row
        checkbox_layout = QHBoxLayout()
        self.recursive = QCheckBox(self.tr("递归搜索输入"))
        self.overwrite = QCheckBox(self.tr("覆盖现有文件"))
        self.clean = QCheckBox(self.tr("清理输出目录"))
        self.flat_layout = QCheckBox(self.tr("平面目录输出"))
        self.merge_short = QCheckBox(self.tr("自动合并短片段"))
        checkbox_layout.addWidget(self.recursive)
        checkbox_layout.addWidget(self.overwrite)
        checkbox_layout.addWidget(self.clean)
        checkbox_layout.addWidget(self.flat_layout)
        checkbox_layout.addWidget(self.merge_short)
        options_layout.addLayout(checkbox_layout)

        # Input fields in two columns
        input_fields_layout = QGridLayout()
        self.num_workers = QSpinBox()
        self.num_workers.setRange(1, 32)
        self.num_workers.setValue(4)
        self.min_duration = QDoubleSpinBox()
        self.max_duration = QDoubleSpinBox()
        self.min_duration.setRange(0, 100)
        self.max_duration.setRange(0, 100)
        self.min_duration.setValue(2.0)
        self.max_duration.setValue(10.0)
        self.min_silence_duration = QDoubleSpinBox()
        self.min_silence_duration.setRange(0, 10)
        self.min_silence_duration.setValue(0.3)
        self.top_db = QSpinBox()
        self.top_db.setRange(-100, 0)
        self.top_db.setValue(-40)
        self.hop_length = QSpinBox()
        self.hop_length.setRange(1, 1000)
        self.hop_length.setValue(10)
        self.max_silence_kept = QDoubleSpinBox()
        self.max_silence_kept.setRange(0, 10)
        self.max_silence_kept.setValue(0.5)

        input_fields_layout.addWidget(QLabel(self.tr("工作进程:")), 0, 0)
        input_fields_layout.addWidget(self.num_workers, 0, 1)
        input_fields_layout.addWidget(QLabel(self.tr("最小时长:")), 0, 2)
        input_fields_layout.addWidget(self.min_duration, 0, 3)
        input_fields_layout.addWidget(QLabel(self.tr("最大时长:")), 1, 0)
        input_fields_layout.addWidget(self.max_duration, 1, 1)
        input_fields_layout.addWidget(QLabel(self.tr("最小静音:")), 1, 2)
        input_fields_layout.addWidget(self.min_silence_duration, 1, 3)
        input_fields_layout.addWidget(QLabel(self.tr("静音阈值:")), 2, 0)
        input_fields_layout.addWidget(self.top_db, 2, 1)
        input_fields_layout.addWidget(QLabel(self.tr("Hop长度:")), 2, 2)
        input_fields_layout.addWidget(self.hop_length, 2, 3)
        input_fields_layout.addWidget(QLabel(self.tr("最大保留静音:")), 3, 0)
        input_fields_layout.addWidget(self.max_silence_kept, 3, 1)  # row, column, occupying row, occupying columns
        input_fields_layout.addWidget(QLabel(self.tr("注：如果输出为空请检查输入文件格式,推荐转为wav")), 3, 2, 1, 2)

        options_layout.addLayout(input_fields_layout)
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)

        # Run button
        self.run_button = QPushButton(self.tr("运行音频切片"))
        self.run_button.clicked.connect(self.run_slice_audio)
        layout.addWidget(self.run_button)

        # Output display
        self.output_display = QTextEdit()
        self.output_display.setReadOnly(True)
        layout.addWidget(self.output_display)

        self.setLayout(layout)
        self.set_tooltips()

    def set_tooltips(self):
        self.recursive.setToolTip(self.tr("递归搜索输入目录的子目录"))
        self.overwrite.setToolTip(self.tr("覆盖已存在的同名文件"))
        self.clean.setToolTip(self.tr("处理前清理输出目录"))
        self.num_workers.setToolTip(self.tr("用于处理的工作进程数，不建议大于CPU核心数"))
        self.min_duration.setToolTip(self.tr("每个切片的最小持续时间（秒）"))
        self.max_duration.setToolTip(self.tr("每个切片的最大持续时间（秒）"))
        self.min_silence_duration.setToolTip(self.tr("静音的最小持续时间（秒）"))
        self.top_db.setToolTip(self.tr("librosa.effects.split的top_db参数，低于该值（分贝）视为静音"))
        self.hop_length.setToolTip(self.tr("librosa.effects.split的hop_length参数，值为分析帧之间的样本数量"))
        self.max_silence_kept.setToolTip(self.tr("保留的最大静音持续时间（秒）"))
        self.flat_layout.setToolTip(self.tr("使用平面目录结构输出"))
        self.merge_short.setToolTip(self.tr("自动合并短切片到最小时长"))

    def browse_directory(self, line_edit):
        directory = QFileDialog.getExistingDirectory(self, self.tr("选择目录"))
        if directory:
            line_edit.setText(directory)
            self.save_settings()

    def run_slice_audio(self):
        input_dir = self.input_dir.text()
        output_dir = self.output_dir.text()

        if not input_dir or not output_dir:
            QMessageBox.warning(self, self.tr("错误"), self.tr("请选择输入和输出目录。"))
            return

        command = ["fap", "slice-audio-v2"]

        if self.recursive.isChecked():
            command.append("--recursive")
        else:
            command.append("--no-recursive")
        if self.overwrite.isChecked():
            command.append("--overwrite")
        else:
            command.append("--no-overwrite")
        if self.clean.isChecked():
            command.append("--clean")
        else:
            command.append("--no-clean")

        command.extend([
            "--num-workers", str(self.num_workers.value()),
            "--min-duration", str(self.min_duration.value()),
            "--max-duration", str(self.max_duration.value()),
            "--min-silence-duration", str(self.min_silence_duration.value()),
            "--top-db", str(self.top_db.value()),
            "--hop-length", str(self.hop_length.value()),
            "--max-silence-kept", str(self.max_silence_kept.value())
        ])

        if self.flat_layout.isChecked():
            command.append("--flat-layout")
        else:
            command.append("--no-flat-layout")
        if self.merge_short.isChecked():
            command.append("--merge-short")
        else:
            command.append("--no-merge-short")

        command.extend([input_dir, output_dir])

        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.finished.connect(self.process_finished)

        self.run_button.setEnabled(False)
        self.output_display.clear()
        self.output_display.append(self.tr("处理中..."))

        self.process.start(command[0], command[1:])

    def handle_stdout(self):
        data = self.process.readAllStandardOutput()
        stdout = self.decode_output(data)
        self.output_display.append(stdout)

    def handle_stderr(self):
        data = self.process.readAllStandardError()
        stderr = self.decode_output(data)
        self.output_display.append(stderr)

    def decode_output(self, data):
        encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'cp936']

        for encoding in encodings:
            try:
                decoded = bytes(data).decode(encoding)
                return self.format_output(decoded)
            except UnicodeDecodeError:
                continue

        # If all attempts fail, use 'replace' error handler with the default system encoding
        decoded = bytes(data).decode(sys.getdefaultencoding(), errors='replace')
        return self.format_output(decoded)

    def format_output(self, text):
        # Remove the module path information from log lines
        pattern = r'[\w.]+:\w+:\d+ - '
        formatted = re.sub(pattern, '', text)
        return formatted.strip()

    def process_finished(self):
        self.run_button.setEnabled(True)
        self.output_display.append(self.tr("处理完成。"))
        QMessageBox.information(self, self.tr("处理完成"), self.tr("音频切片处理已完成。"))

    def save_settings(self):
        self.settings.setValue("slicer_input_path", self.input_dir.text())
        self.settings.setValue("slicer_output_path", self.output_dir.text())

    def load_settings(self):
        self.input_dir.setText(self.settings.value("slicer_input_path", ""))
        self.output_dir.setText(self.settings.value("slicer_output_path", ""))

    def open_directory(self, line_edit):
        directory = line_edit.text()
        if directory and os.path.isdir(directory):
            os.startfile(directory)
        else:
            QMessageBox.warning(self, self.tr("错误"), self.tr("无效的目录路径"))
