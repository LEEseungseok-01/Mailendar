import sys
import subprocess
import json
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QLabel, 
                             QSystemTrayIcon, QMenu, QStyle)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QRect
from PyQt6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor, QFont

# 비서 엔진 불러오기
from bc_worker import BackgroundWorker 

class NotificationPopup(QWidget):
    """알림 팝업 디자인 클래스"""
    def __init__(self, title, message):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | 
                            Qt.WindowType.WindowStaysOnTopHint | 
                            Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.setStyleSheet("""
            QWidget { background-color: #FFFFFF; border: 2px solid #E74C3C; border-radius: 10px; }
            QLabel#title { font-weight: bold; color: #E74C3C; font-size: 14px; border: none; }
            QLabel#msg { color: #333333; font-size: 12px; border: none; }
        """)

        layout = QVBoxLayout()
        self.title_label = QLabel(title); self.title_label.setObjectName("title")
        self.msg_label = QLabel(message); self.msg_label.setObjectName("msg")
        self.msg_label.setWordWrap(True)
        
        layout.addWidget(self.title_label)
        layout.addWidget(self.msg_label)
        self.setLayout(layout)
        self.setFixedSize(300, 100)

class MainApp(QWidget):
    def __init__(self):
        super().__init__()
        self.popups = []
        self.init_ui()
        
        # 비서 엔진 시작 및 신호 연결
        self.worker = BackgroundWorker()
        self.worker.notification_signal.connect(self.show_notification)
        self.worker.review_count_signal.connect(self.update_tray_icon)
        self.worker.start()

    def init_ui(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.update_tray_icon(0) # 초기화
        
        menu = QMenu()
        open_action = QAction("대시보드 열기", self)
        open_action.triggered.connect(self.launch_streamlit)
        quit_action = QAction("종료", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        
        menu.addAction(open_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.show()

    def update_tray_icon(self, count):
        """시스템 트레이 아이콘에 숫자 배지 그리기"""
        pixmap = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon).pixmap(24, 24)
        
        if count > 0:
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor("#E74C3C"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(12, 0, 12, 12) # 우측 상단
            
            painter.setPen(QColor("white"))
            painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))
            text = str(count) if count < 10 else "9+"
            painter.drawText(QRect(12, 0, 12, 12), Qt.AlignmentFlag.AlignCenter, text)
            painter.end()
            
        self.tray_icon.setIcon(QIcon(pixmap))

    def launch_streamlit(self):
        subprocess.Popen(["streamlit", "run", "t6.py"])

    def show_notification(self, title, message):
        """알림 창 생성 및 세로 쌓기 로직"""
        popup = NotificationPopup(title, message)
        offset = len(self.popups) * (popup.height() + 10)
        screen = QApplication.primaryScreen().availableGeometry()
        new_y = screen.height() - popup.height() - 50 - offset
        popup.move(screen.width() - popup.width() - 20, new_y)
        
        self.popups.append(popup)
        popup.show()
        QTimer.singleShot(10000, lambda: self.close_notification(popup))

    def close_notification(self, popup):
        if popup in self.popups:
            popup.close()
            self.popups.remove(popup)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainApp()
    sys.exit(app.exec())