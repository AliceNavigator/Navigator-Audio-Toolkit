import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QCheckBox, QSpinBox, QTextEdit, QFileDialog,
                             QDoubleSpinBox, QGroupBox, QGridLayout, QMessageBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSettings
from PyQt5.QtGui import QFont, QColor
import subprocess
import re
import locale
import html
import win32process
import win32con


class FapAnalysisTab(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.settings = QSettings('Settings.ini', QSettings.IniFormat)
        self.load_settings()

    def initUI(self):
        main_layout = QVBoxLayout()

        # Input Directory Section
        input_layout = QHBoxLayout()
        self.input_dir = QLineEdit()
        self.input_dir.setToolTip(self.tr("选择要分析的音频文件所在的目录"))
        browse_btn = QPushButton(self.tr("选择输入目录"))
        browse_btn.clicked.connect(self.browse_directory)
        input_layout.addWidget(QLabel(self.tr("输入目录:")))
        input_layout.addWidget(self.input_dir)
        input_layout.addWidget(browse_btn)
        input_layout.addWidget(QPushButton(self.tr("打开"), clicked=lambda: self.open_directory(self.input_dir)))
        main_layout.addLayout(input_layout)

        # Analysis Options Section
        options_layout = QHBoxLayout()

        # Frequency Analysis Section
        frequency_group = QGroupBox(self.tr("频率分析"))
        frequency_layout = QGridLayout()

        self.freq_recursive = QCheckBox(self.tr("递归搜索"))
        self.freq_recursive.setToolTip(self.tr("在子目录中也搜索音频文件"))
        self.freq_visualize = QCheckBox(self.tr("可视化"))
        self.freq_visualize.setToolTip(self.tr("生成频率分布的可视化图表"))
        self.freq_workers = QSpinBox()
        self.freq_workers.setRange(1, 16)
        self.freq_workers.setValue(4)
        self.freq_workers.setToolTip(self.tr("设置并行处理的工作进程数"))

        info_label = QLabel(self.tr("注意：仅支持wav文件输入"))
        info_label.setWordWrap(True)
        info_label.setAlignment(Qt.AlignCenter)
        info_label.setStyleSheet("""
                    border: 2px dashed #808080;
                    border-radius: 5px;
                    padding: 5px;
                    background-color: #F0F0F0;
                """)

        frequency_layout.addWidget(self.freq_recursive, 0, 0)
        frequency_layout.addWidget(self.freq_visualize, 1, 0)
        frequency_layout.addWidget(info_label, 0, 1, 2, 2)
        frequency_layout.addWidget(QLabel(self.tr("工作进程数:")), 2, 0)
        frequency_layout.addWidget(self.freq_workers, 2, 1, 1, 2)
        frequency_layout.setColumnStretch(0, 1)
        frequency_layout.setColumnStretch(1, 1)
        frequency_layout.setColumnStretch(2, 1)
        frequency_group.setLayout(frequency_layout)

        # Length Analysis Section
        length_group = QGroupBox(self.tr("时长分析"))
        length_layout = QGridLayout()

        self.len_recursive = QCheckBox(self.tr("递归搜索"))
        self.len_recursive.setToolTip(self.tr("在子目录中也搜索音频文件"))
        self.len_visualize = QCheckBox(self.tr("可视化"))
        self.len_visualize.setToolTip(self.tr("生成时长分布的可视化图表"))

        self.len_long_check = QCheckBox(self.tr("检测长文件"))
        self.len_long_threshold = QDoubleSpinBox()
        self.len_long_threshold.setRange(0, 3600)
        self.len_long_threshold.setValue(100.0)
        self.len_long_threshold.setToolTip(self.tr("设置长文件的阈值（秒）"))

        self.len_short_check = QCheckBox(self.tr("检测短文件"))
        self.len_short_threshold = QDoubleSpinBox()
        self.len_short_threshold.setRange(0, 3600)
        self.len_short_threshold.setValue(2.0)
        self.len_short_threshold.setToolTip(self.tr("设置短文件的阈值（秒）"))

        self.len_workers = QSpinBox()
        self.len_workers.setRange(1, 16)
        self.len_workers.setValue(4)
        self.len_workers.setToolTip(self.tr("设置并行处理的工作进程数"))

        length_layout.addWidget(self.len_recursive, 0, 0)
        length_layout.addWidget(self.len_visualize, 1, 0)
        length_layout.addWidget(self.len_long_check, 0, 1)
        length_layout.addWidget(self.len_long_threshold, 0, 2)
        length_layout.addWidget(self.len_short_check, 1, 1)
        length_layout.addWidget(self.len_short_threshold, 1, 2)
        length_layout.addWidget(QLabel(self.tr("工作进程数:")), 2, 0)
        length_layout.addWidget(self.len_workers, 2, 1, 1, 2)
        length_layout.setColumnStretch(0, 1)
        length_layout.setColumnStretch(1, 1)
        length_layout.setColumnStretch(2, 1)
        length_group.setLayout(length_layout)

        options_layout.addWidget(frequency_group)
        options_layout.addWidget(length_group)
        main_layout.addLayout(options_layout)

        # Buttons
        buttons_layout = QHBoxLayout()
        self.freq_analyze_btn = QPushButton(self.tr("分析频率"))
        self.freq_analyze_btn.clicked.connect(self.analyze_frequency)
        self.len_analyze_btn = QPushButton(self.tr("分析时长"))
        self.len_analyze_btn.clicked.connect(self.analyze_length)
        buttons_layout.addWidget(self.freq_analyze_btn)
        buttons_layout.addWidget(self.len_analyze_btn)
        main_layout.addLayout(buttons_layout)

        # Output Section
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        main_layout.addWidget(QLabel(self.tr("输出结果:")))
        main_layout.addWidget(self.output_text)

        self.setLayout(main_layout)

    def browse_directory(self):
        directory = QFileDialog.getExistingDirectory(self, self.tr("选择目录"))
        if directory:
            self.input_dir.setText(directory)
            self.save_settings()

    def analyze_frequency(self):
        self.output_text.clear()
        self.output_text.append(self.tr("开始进行频率分析..."))
        input_dir = self.input_dir.text()
        if not input_dir:
            self.output_text.append(self.tr("请选择输入目录"))
            return

        cmd = ["fap", "frequency", input_dir]
        if self.freq_recursive.isChecked():
            cmd.append("--recursive")
        else:
            cmd.append("--no-recursive")
        if self.freq_visualize.isChecked():
            cmd.append("--visualize")
        else:
            cmd.append("--no-visualize")
        cmd.extend(["--num-workers", str(self.freq_workers.value())])

        self.disable_analysis_buttons()
        self.run_command(cmd)

    def analyze_length(self):
        self.output_text.clear()
        self.output_text.append(self.tr("开始进行时长分析..."))
        input_dir = self.input_dir.text()
        if not input_dir:
            self.output_text.append(self.tr("请选择输入目录"))
            return

        cmd = ["fap", "length", input_dir]
        if self.len_recursive.isChecked():
            cmd.append("--recursive")
        else:
            cmd.append("--no-recursive")
        if self.len_visualize.isChecked():
            cmd.append("--visualize")
        else:
            cmd.append("--no-visualize")
        cmd.append("--no-accurate")
        if self.len_long_check.isChecked():
            cmd.extend(["-l", str(self.len_long_threshold.value())])
        if self.len_short_check.isChecked():
            cmd.extend(["-s", str(self.len_short_threshold.value())])
        cmd.extend(["-w", str(self.len_workers.value())])

        self.disable_analysis_buttons()
        self.run_command(cmd)

    def run_command(self, cmd):
        self.worker = CommandWorker(cmd)
        self.worker.output_ready.connect(self.update_output)
        self.worker.finished.connect(self.command_finished)
        self.worker.error_occurred.connect(self.command_error)
        self.worker.start()

    def disable_analysis_buttons(self):
        self.freq_analyze_btn.setEnabled(False)
        self.len_analyze_btn.setEnabled(False)

    def enable_analysis_buttons(self):
        self.freq_analyze_btn.setEnabled(True)
        self.len_analyze_btn.setEnabled(True)

    def update_output(self, output):
        output = self.unescape_unicode(output)
        output = re.sub(r'fish_audio_preprocess\.cli\.[a-z]+:[a-z]+:\d+\s-\s', '', output)
        translations = {
            "Total duration:": self.tr("总时长:"),
            "Average duration:": self.tr("平均时长:"),
            "Max duration:": self.tr("最大时长:"),
            "Min duration:": self.tr("最小时长:"),
            "Average samplerate:": self.tr("平均采样率:"),
            "Found": self.tr("发现"),
            "files": self.tr("个文件"),
            "calculating length": self.tr("正在计算时长"),
            "longer than": self.tr("长于"),
            "shorter than": self.tr("短于"),
            "seconds": self.tr("秒")
        }
        for eng, chn in translations.items():
            output = output.replace(eng, chn)

        if "INFO" in output:
            color = QColor("blue")
            weight = QFont.Normal
        elif "WARNING" in output:
            color = QColor("orange")
            weight = QFont.Bold
        elif "ERROR" in output:
            color = QColor("red")
            weight = QFont.Bold
        else:
            color = QColor("black")
            weight = QFont.Normal

        self.output_text.setTextColor(color)
        self.output_text.setFontWeight(weight)
        self.output_text.append(output)

    def unescape_unicode(self, text):
        def replace_unicode(match):
            return chr(int(match.group(1), 16))

        text = re.sub(r'\\u([0-9a-fA-F]{4})', replace_unicode, text)
        text = text.replace('G\\u266f', 'G#')
        text = text.replace('A\\u266f', 'A#')
        text = text.replace('C\\u266f', 'C#')
        text = text.replace('D\\u266f', 'D#')
        text = text.replace('F\\u266f', 'F#')
        text = html.unescape(text)
        return text

    def command_finished(self):
        self.output_text.setTextColor(QColor("green"))
        self.output_text.setFontWeight(QFont.Bold)
        self.output_text.append(self.tr("分析完成"))
        self.output_text.setTextColor(QColor("black"))
        self.output_text.setFontWeight(QFont.Normal)
        self.enable_analysis_buttons()

    def command_error(self, error_message):
        self.output_text.setTextColor(QColor("red"))
        self.output_text.setFontWeight(QFont.Bold)
        self.output_text.append(f"错误: {error_message}")
        self.output_text.setTextColor(QColor("black"))
        self.output_text.setFontWeight(QFont.Normal)
        self.enable_analysis_buttons()

    def save_settings(self):
        self.settings.setValue("analysis_input_path", self.input_dir.text())

    def load_settings(self):
        self.input_dir.setText(self.settings.value("analysis_input_path", ""))

    def open_directory(self, line_edit):
        directory = line_edit.text()
        if directory and os.path.isdir(directory):
            os.startfile(directory)
        else:
            QMessageBox.warning(self, self.tr("错误"), self.tr("无效的目录路径"))


class CommandWorker(QThread):
    output_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, cmd):
        super().__init__()
        self.cmd = cmd

    def run(self):
        try:
            system_encoding = locale.getpreferredencoding()

            # Force Matplotlib to use TkAgg backend to avoid display failures
            env = os.environ.copy()
            env['MPLBACKEND'] = 'TkAgg'

            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = win32con.SW_HIDE

            process = subprocess.Popen(
                self.cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding=system_encoding,
                errors='replace',
                bufsize=1,
                universal_newlines=True,
                startupinfo=startupinfo,
                creationflags=win32process.CREATE_NO_WINDOW,
                env=env
            )

            for line in iter(process.stdout.readline, ''):
                try:
                    decoded_line = line.encode(system_encoding).decode('utf-8')
                except UnicodeDecodeError:
                    decoded_line = line
                self.output_ready.emit(decoded_line.strip())

            process.wait()
            if process.returncode != 0:
                self.error_occurred.emit(f"命令执行失败，返回码: {process.returncode}")
        except Exception as e:
            self.error_occurred.emit(str(e))
