import sys
import serial
import struct
import time
import os
import numpy as np
import cv2
import warnings
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QGridLayout, QPushButton, QLabel, 
                             QProgressBar, QMessageBox, QFrame, QSpacerItem, QSizePolicy)
from PyQt6.QtGui import QPainter, QPen, QPixmap, QColor, QImage, QFont
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import MinMaxScaler

warnings.filterwarnings("ignore")

# ==============================================================================
# CONFIGURAÇÃO DE HARDWARE
# ==============================================================================
SERIAL_PORT = 'COM6'
BAUD_RATE   = 921600

REG_STATUS, REG_CMD, REG_CONFIG     = 0x00, 0x04, 0x08
REG_WRITE_W, REG_WRITE_A, REG_READ_OUT = 0x10, 0x14, 0x18
REG_QUANT_CFG, REG_QUANT_MULT, REG_BIAS_BASE = 0x40, 0x44, 0x80

CMD_RST_DMA_PTRS = (1 << 0)
CMD_START        = (1 << 1)
CMD_ACC_CLEAR    = (1 << 2)
CMD_RST_W_RD, CMD_RST_I_RD = (1 << 4), (1 << 5)
CMD_RST_WR_W, CMD_RST_WR_I = (1 << 6), (1 << 7)

STATUS_OUT_VALID = (1 << 3)
STATUS_DONE      = (1 << 1)

# ==============================================================================
# ESTILO PROFISSIONAL (CSS)
# ==============================================================================
STYLESHEET = """
QMainWindow { background-color: #0F0F12; }

/* Paineis (Cards) */
QFrame#Panel { 
    background-color: #1A1A1E; 
    border: 1px solid #333; 
    border-radius: 8px; 
}

/* Textos */
QLabel { color: #E0E0E0; font-family: 'Segoe UI', sans-serif; }
QLabel#Header { font-size: 11px; font-weight: bold; color: #888; letter-spacing: 1px; text-transform: uppercase; }
QLabel#BigResult { font-family: 'Consolas', monospace; font-size: 140px; color: #00FFFF; font-weight: bold; }
QLabel#ScoreLabel { font-family: 'Consolas', monospace; font-size: 12px; color: #BBB; }

/* Botões */
QPushButton {
    background-color: #25252A; 
    border: 1px solid #444; 
    color: #FFF;
    padding: 12px; 
    font-weight: 600; 
    border-radius: 6px; 
    font-size: 13px;
}
QPushButton:hover { background-color: #333; border-color: #00FFFF; color: #00FFFF; }
QPushButton:pressed { background-color: #00FFFF; color: #000; }
QPushButton:disabled { color: #555; border-color: #222; background-color: #151518; }

QPushButton#ActionBtn { background-color: #004400; border-color: #006600; }
QPushButton#ActionBtn:hover { background-color: #006600; border-color: #00FF00; color: #FFF; }

/* Barras de Progresso */
QProgressBar {
    border: none;
    background-color: #2A2A30;
    border-radius: 3px;
    height: 6px;
    text-align: right;
}
QProgressBar::chunk { background-color: #00FFFF; border-radius: 3px; }
"""

# ==============================================================================
# DRIVER NPU
# ==============================================================================
class NPUDriver:
    def __init__(self, port, baud):
        self.ser = serial.Serial(port, baud, timeout=1.0)
        self.ser.reset_input_buffer()

    def close(self): self.ser.close()

    def write_reg(self, addr, data):
        self.ser.write(struct.pack('>B I I', 0x01, addr, int(data) & 0xFFFFFFFF))

    def write_burst(self, addr, data_list):
        header = struct.pack('>B I', 0x01, addr)
        buf = bytearray()
        for d in data_list:
            buf.extend(header)
            buf.extend(struct.pack('>I', int(d) & 0xFFFFFFFF))
        self.ser.write(buf)

    def read_reg(self, addr):
        self.ser.write(struct.pack('>B I', 0x02, addr))
        resp = self.ser.read(4)
        return struct.unpack('>I', resp)[0] if len(resp) == 4 else 0

    def wait_done(self):
        while not (self.read_reg(REG_STATUS) & STATUS_DONE): pass

    def read_results(self):
        res = []
        for _ in range(4):
            while not (self.read_reg(REG_STATUS) & STATUS_OUT_VALID): pass
            val = self.read_reg(REG_READ_OUT)
            res.append(self.unpack_int8(val))
            self.read_reg(REG_STATUS)
        return res[::-1]

    def pack_int8(self, v):
        return ((int(v[0]) & 0xFF)) | ((int(v[1]) & 0xFF) << 8) | \
               ((int(v[2]) & 0xFF) << 16) | ((int(v[3]) & 0xFF) << 24)

    def unpack_int8(self, p):
        return [(p >> (i*8) & 0xFF) - 256 if (p >> (i*8) & 0xFF) & 0x80 else (p >> (i*8) & 0xFF) for i in range(4)]

# ==============================================================================
# WORKER THREAD
# ==============================================================================
class ModelWorker(QThread):
    finished = pyqtSignal(object, object, object, object) 

    def run(self):
        if not os.path.exists("mnist.npz"):
            import urllib.request
            urllib.request.urlretrieve("https://storage.googleapis.com/tensorflow/tf-keras-datasets/mnist.npz", "mnist.npz")
        
        with np.load("mnist.npz", allow_pickle=True) as f:
            x_train, y_train = f['x_train'], f['y_train']
        
        X_train = x_train.reshape(-1, 784).astype(np.float32) / 255.0
        
        clf = LogisticRegression(solver='saga', max_iter=200, tol=1e-2, C=0.05)
        clf.fit(X_train, y_train)

        max_w = np.max(np.abs(clf.coef_))
        scale_w = 127.0 / max_w
        scale_x = 127.0 
        
        # Quantização
        W_int = np.clip(np.round(clf.coef_.T * scale_w), -127, 127).astype(int)
        B_int = np.clip(np.round(clf.intercept_ * scale_w * scale_x), -200000, 200000).astype(int)

        # Calibração Segura (99.9%)
        sim_input = (X_train[:500] * scale_x).astype(int) 
        sim_acc = np.dot(sim_input, W_int) + B_int
        max_acc_calib = np.percentile(np.abs(sim_acc), 99.9)
        
        best_shift = 16
        best_mult = int(round((127.0 / max_acc_calib) * (1 << best_shift)))
        if best_mult < 1: best_mult = 1

        self.finished.emit(W_int, B_int, best_mult, best_shift)

# ==============================================================================
# CANVAS
# ==============================================================================
class DrawCanvas(QLabel):
    def __init__(self):
        super().__init__()
        self.setFixedSize(280, 280) 
        self.setStyleSheet("border: 1px solid #333; background-color: #000; border-radius: 4px;")
        self.pixmap = QPixmap(280, 280)
        self.pixmap.fill(Qt.GlobalColor.black)
        self.setPixmap(self.pixmap)
        self.last_point = None
        self.pen_color = QColor(255, 255, 255) 
        self.pen_size = 32

    def mouseMoveEvent(self, e):
        if self.last_point:
            painter = QPainter(self.pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(self.pen_color, self.pen_size, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawLine(self.last_point, e.position())
            painter.end()
            self.setPixmap(self.pixmap)
            self.last_point = e.position()
            self.update()

    def mousePressEvent(self, e):
        self.last_point = e.position()

    def mouseReleaseEvent(self, e):
        self.last_point = None

    def clear_canvas(self):
        self.pixmap.fill(Qt.GlobalColor.black)
        self.setPixmap(self.pixmap)
        self.update()

    def get_mnist_image(self):
        ptr = self.pixmap.toImage().bits()
        ptr.setsize(self.pixmap.width() * self.pixmap.height() * 4)
        arr = np.frombuffer(ptr, np.uint8).reshape((280, 280, 4))
        gray = cv2.cvtColor(arr, cv2.COLOR_RGBA2GRAY)

        coords = cv2.findNonZero(gray)
        if coords is None: return np.zeros(784, dtype=int), np.zeros((28,28), dtype=np.uint8)
        
        x, y, w, h = cv2.boundingRect(coords)
        padding = 40
        x = max(0, x - padding); y = max(0, y - padding)
        w = min(280 - x, w + 2*padding); h = min(280 - y, h + 2*padding)
        digit = gray[y:y+h, x:x+w]

        if w > h: scale = 20.0 / w
        else: scale = 20.0 / h
        nw, nh = int(w*scale), int(h*scale)
        if nw<=0: nw=1
        if nh<=0: nh=1
        digit_resized = cv2.resize(digit, (nw, nh), interpolation=cv2.INTER_AREA)

        moments = cv2.moments(digit_resized)
        cx = int(moments['m10']/moments['m00']) if moments['m00']!=0 else nw//2
        cy = int(moments['m01']/moments['m00']) if moments['m00']!=0 else nh//2

        final_img = np.zeros((28, 28), dtype=np.uint8)
        origin_x, origin_y = 14 - cx, 14 - cy
        
        start_y, start_x = max(0, origin_y), max(0, origin_x)
        end_y, end_x = min(28, start_y + nh), min(28, start_x + nw)
        src_y = 0 if origin_y >=0 else -origin_y
        src_x = 0 if origin_x >=0 else -origin_x
        src_h, src_w = end_y - start_y, end_x - start_x

        if src_h > 0 and src_w > 0:
            final_img[start_y:end_y, start_x:end_x] = digit_resized[src_y:src_y+src_h, src_x:src_x+src_w]

        quantized = (final_img.astype(float) / 255.0 * 127.0).astype(int)
        return quantized.flatten(), final_img

# ==============================================================================
# MAIN WINDOW
# ==============================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NPU RISC-V HARVESTER - MNIST PRO")
        self.setFixedSize(1000, 600)
        
        self.W_int = None; self.B_int = None; self.mult = 1; self.shift = 0; self.npu = None
        self.setup_ui()
        
        self.status_label.setText("INITIALIZING SYSTEM & TRAINING MODEL...")
        self.worker = ModelWorker()
        self.worker.finished.connect(self.on_model_ready)
        self.worker.start()

    def setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        # ---------------------------------------------------------
        # COLUNA 1: INPUT & CONTROLE
        # ---------------------------------------------------------
        col1 = QVBoxLayout()
        
        # Painel de Desenho
        panel_draw = QFrame(); panel_draw.setObjectName("Panel")
        layout_draw = QVBoxLayout(panel_draw)
        
        lbl_head1 = QLabel("OPTICAL SENSOR INPUT"); lbl_head1.setObjectName("Header")
        self.canvas = DrawCanvas()
        
        btn_row = QHBoxLayout()
        self.btn_clear = QPushButton("CLEAR"); self.btn_clear.clicked.connect(self.canvas.clear_canvas)
        self.btn_infer = QPushButton("INFER (FPGA)"); self.btn_infer.setObjectName("ActionBtn")
        self.btn_infer.clicked.connect(self.run_inference); self.btn_infer.setEnabled(False)
        btn_row.addWidget(self.btn_clear); btn_row.addWidget(self.btn_infer)

        layout_draw.addWidget(lbl_head1)
        layout_draw.addSpacing(10)
        layout_draw.addWidget(self.canvas, alignment=Qt.AlignmentFlag.AlignCenter)
        layout_draw.addSpacing(15)
        layout_draw.addLayout(btn_row)
        layout_draw.addStretch()

        # Painel de Debug (Visão FPGA)
        panel_debug = QFrame(); panel_debug.setObjectName("Panel")
        layout_debug = QHBoxLayout(panel_debug)
        self.lbl_debug = QLabel(); self.lbl_debug.setFixedSize(80, 80)
        self.lbl_debug.setStyleSheet("background-color: black; border: 1px solid #333;")
        self.lbl_debug.setScaledContents(True)
        
        debug_info = QVBoxLayout()
        lbl_head2 = QLabel("NPU VISION"); lbl_head2.setObjectName("Header")
        self.lbl_info_hw = QLabel("Status: Offline"); self.lbl_info_hw.setStyleSheet("color: #666; font-size: 11px;")
        debug_info.addWidget(lbl_head2); debug_info.addWidget(self.lbl_info_hw); debug_info.addStretch()
        
        layout_debug.addLayout(debug_info); layout_debug.addWidget(self.lbl_debug)

        col1.addWidget(panel_draw, 70)
        col1.addWidget(panel_debug, 30)

        # ---------------------------------------------------------
        # COLUNA 2: TELEMETRIA E RESULTADOS
        # ---------------------------------------------------------
        col2 = QVBoxLayout()
        panel_res = QFrame(); panel_res.setObjectName("Panel")
        layout_res = QVBoxLayout(panel_res)

        lbl_head3 = QLabel("CLASSIFICATION RESULT"); lbl_head3.setObjectName("Header")
        
        # Display Principal
        self.lbl_result = QLabel("--"); self.lbl_result.setObjectName("BigResult")
        self.lbl_result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Barras de Progresso
        self.bars = []
        self.labels_pct = []
        
        grid_bars = QGridLayout()
        grid_bars.setSpacing(10)
        
        for i in range(10):
            lbl_num = QLabel(f"{i}"); lbl_num.setStyleSheet("font-weight: bold; color: #FFF;")
            
            bar = QProgressBar(); bar.setRange(0, 100); bar.setValue(0); bar.setTextVisible(False)
            
            lbl_pct = QLabel("0%"); lbl_pct.setObjectName("ScoreLabel"); lbl_pct.setFixedWidth(40)
            lbl_pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            
            grid_bars.addWidget(lbl_num, i, 0)
            grid_bars.addWidget(bar, i, 1)
            grid_bars.addWidget(lbl_pct, i, 2)
            
            self.bars.append(bar)
            self.labels_pct.append(lbl_pct)

        layout_res.addWidget(lbl_head3)
        layout_res.addWidget(self.lbl_result)
        layout_res.addLayout(grid_bars)
        layout_res.addStretch()

        col2.addWidget(panel_res)

        main_layout.addLayout(col1, 45)
        main_layout.addLayout(col2, 55)

        # Status Bar
        self.status_label = QLabel("Initializing...")
        self.statusBar().addWidget(self.status_label)

    def on_model_ready(self, W, B, mult, shift):
        self.W_int = W; self.B_int = B; self.mult = mult; self.shift = shift
        try:
            self.npu = NPUDriver(SERIAL_PORT, BAUD_RATE)
            self.status_label.setText(f"CONNECTED: {SERIAL_PORT} @ {BAUD_RATE}bps | NPU Ready")
            self.lbl_info_hw.setText(f"HW: Connected\nCfg: M={mult} S={shift}")
            
            self.npu.write_reg(REG_QUANT_MULT, self.mult)
            self.npu.write_reg(REG_QUANT_CFG, self.shift)
            self.btn_infer.setEnabled(True)
        except Exception as e:
            self.status_label.setText(f"ERROR: {e}")

    def softmax_temperature(self, x, temperature=5.0):
        # Temperatura > 1.0 "amacia" a distribuição, mostrando os scores secundários
        # Temperatura < 1.0 "endurece", forçando 100% no vencedor
        x = x / temperature 
        e_x = np.exp(x - np.max(x))
        return (e_x / e_x.sum()) * 100

    def run_inference(self):
        if not self.npu: return
        x_vec, debug_img = self.canvas.get_mnist_image()
        
        # Update Debug View
        h, w = debug_img.shape
        qimg = QImage(debug_img.data, w, h, w, QImage.Format.Format_Grayscale8)
        self.lbl_debug.setPixmap(QPixmap.fromImage(qimg))
        
        if np.all(x_vec == 0): return

        t0 = time.time()
        
        # Envia Input
        self.npu.write_reg(REG_CMD, CMD_RST_DMA_PTRS | CMD_RST_WR_W | CMD_RST_WR_I)
        self.npu.write_burst(REG_WRITE_A, [self.npu.pack_int8([x_vec[k], 0, 0, 0]) for k in range(784)])
        
        scores = []
        for start in [0, 4, 8]:
            end = min(start+4, 10); size = end - start
            for b in range(size): self.npu.write_reg(REG_BIAS_BASE + b*4, int(self.B_int[start+b]))
            for b in range(size, 4): self.npu.write_reg(REG_BIAS_BASE + b*4, 0)
            self.npu.write_reg(REG_CMD, CMD_RST_WR_W)
            w_pkt = []
            for k in range(784):
                row = self.W_int[k, start:end]
                padded = np.zeros(4, dtype=int)
                if len(row)>0: padded[:len(row)] = row
                w_pkt.append(self.npu.pack_int8(padded))
            self.npu.write_burst(REG_WRITE_W, w_pkt)
            self.npu.write_reg(REG_CONFIG, 784)
            self.npu.write_reg(REG_CMD, CMD_START | CMD_RST_W_RD | CMD_RST_I_RD | CMD_ACC_CLEAR)
            self.npu.wait_done()
            scores.extend(self.npu.read_results()[0][:size])
            
        dt = (time.time()-t0)*1000
        
        # Processamento com Temperatura
        # T=8.0 empírico para scores que vão de -128 a 127
        probs = self.softmax_temperature(np.array(scores), temperature=8.0) 
        pred = np.argmax(probs)
        
        self.lbl_result.setText(str(pred))
        self.status_label.setText(f"Inference Latency: {dt:.0f} ms | Top Confidence: {probs[pred]:.1f}%")
        
        for i, p in enumerate(probs):
            self.bars[i].setValue(int(p))
            self.labels_pct[i].setText(f"{p:.1f}%")
            
            # Styling dinâmico
            if i == pred:
                self.bars[i].setStyleSheet("QProgressBar::chunk { background-color: #00FF00; }")
                self.labels_pct[i].setStyleSheet("color: #00FF00; font-weight: bold;")
            elif p > 10.0:
                self.bars[i].setStyleSheet("QProgressBar::chunk { background-color: #FFAA00; }")
                self.labels_pct[i].setStyleSheet("color: #FFAA00;")
            else:
                self.bars[i].setStyleSheet("QProgressBar::chunk { background-color: #333; }")
                self.labels_pct[i].setStyleSheet("color: #555;")

    def closeEvent(self, e):
        if self.npu: self.npu.close()
        e.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv); app.setStyleSheet(STYLESHEET)
    window = MainWindow(); window.show()
    sys.exit(app.exec())