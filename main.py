import cv2
import numpy as np
import time
import queue
import threading
import csv
import os
import win32com.client
from collections import deque, Counter
from datetime import datetime

# ================================================================
# CONFIGURAÇÕES
# ================================================================
ALTURA_REAL_CARRO = 1.5
FOCAL_PX_ESTIMADA = 960
DISTANCIA_PERIGO = 15.0
DISTANCIA_MUITO_PROXIMA = 5.0
AREA_MINIMA_VEICULO = 3000
INTERVALO_FALA_MIN = 2.0
INTERVALO_CONTEXTO = 10.0
HISTORICO_DECISAO = 15

VOZ_RATE = 0
VOZ_VOLUME = 100

# Configurações do CSV
ARQUIVO_CSV = "metricas_tcc.csv"
INTERVALO_LOG = 1.0   # segundos entre linhas no CSV


# ================================================================
# LUMINOSIDADE
# ================================================================
def detectar_luminosidade(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    brilho = float(np.mean(hsv[:, :, 2]))
    if brilho > 150:
        return 'dia', brilho
    elif brilho > 80:
        return 'crepusculo', brilho
    return 'noite', brilho


def ajustar_limiares(modo):
    if modo == 'dia':
        return {'verde_min': np.array([40, 50, 50]), 'verde_max': np.array([90, 255, 255]),
                'branco_min': np.array([0, 0, 160]), 'branco_max': np.array([180, 70, 255])}
    elif modo == 'crepusculo':
        return {'verde_min': np.array([35, 40, 40]), 'verde_max': np.array([85, 255, 255]),
                'branco_min': np.array([0, 0, 130]), 'branco_max': np.array([180, 90, 255])}
    return {'verde_min': np.array([30, 30, 30]), 'verde_max': np.array([80, 255, 255]),
            'branco_min': np.array([0, 0, 100]), 'branco_max': np.array([180, 110, 255])}


# ================================================================
# DISTÂNCIA
# ================================================================
ALTURAS_REAIS = {'car': 1.5, 'motorbike': 1.2, 'bus': 3.2, 'truck': 3.5}


def estimar_distancia(h_px, classe='car', focal=FOCAL_PX_ESTIMADA):
    if h_px < 5:
        return 999.0
    altura_real = ALTURAS_REAIS.get(classe, 1.5)
    return min((altura_real * focal) / h_px, 999.0)


# ================================================================
# LOGGER CSV (SIMPLES)
# ================================================================
class LoggerCSV:
    def __init__(self, arquivo=ARQUIVO_CSV):
        self.arquivo = arquivo
        self.ultimo_log = 0.0
        self._inicializar()

    def _inicializar(self):
        with open(self.arquivo, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp', 'frame', 'fps', 'modo', 'brilho',
                'carro_detectado', 'carro_proximo', 'aproximando',
                'carros_parados', 'faixa_detectada', 'n_listras',
                'semaforo_cor', 'semaforo_tipo',
                'zona_esq', 'zona_cen', 'zona_dir',
                'decisao', 'orientacao'
            ])
        print(f"📊 CSV criado: {self.arquivo}")

    def logar(self, dados):
        agora = time.time()
        if agora - self.ultimo_log < INTERVALO_LOG:
            return
        self.ultimo_log = agora

        with open(self.arquivo, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().isoformat(),
                dados.get('frame', 0),
                f"{dados.get('fps', 0):.1f}",
                dados.get('modo', ''),
                f"{dados.get('brilho', 0):.0f}",
                dados.get('carro_detectado', False),
                dados.get('carro_proximo', False),
                dados.get('aproximando', False),
                dados.get('carros_parados', 0),
                dados.get('faixa_detectada', False),
                dados.get('n_listras', 0),
                dados.get('semaforo_cor', ''),
                dados.get('semaforo_tipo', ''),
                dados.get('zona_esq', 0),
                dados.get('zona_cen', 0),
                dados.get('zona_dir', 0),
                dados.get('decisao', ''),
                dados.get('orientacao', '') or ''
            ])


# ================================================================
# RASTREADOR DE VEÍCULOS
# ================================================================
class RastreadorVeiculos:
    def __init__(self, max_idade=2.0):
        self.veiculos = {}
        self.proximo_id = 0
        self.max_idade = max_idade

    def _iou(self, b1, b2):
        x1, y1, w1, h1 = b1
        x2, y2, w2, h2 = b2
        xi1, yi1 = max(x1, x2), max(y1, y2)
        xi2, yi2 = min(x1 + w1, x2 + w2), min(y1 + h1, y2 + h2)
        inter = max(0, xi2 - xi1) * max(0, yi2 - yi1)
        if inter == 0:
            return 0.0
        uniao = w1 * h1 + w2 * h2 - inter
        return inter / uniao if uniao > 0 else 0.0

    def atualizar(self, deteccoes):
        agora = time.time()
        resultados = []
        ids_usados = set()

        for bbox in deteccoes:
            melhor_id = None
            melhor_iou = 0.3
            for vid, historico in self.veiculos.items():
                if vid in ids_usados or not historico:
                    continue
                _, ultimo_bbox = historico[-1]
                iou = self._iou(bbox, ultimo_bbox)
                if iou > melhor_iou:
                    melhor_iou = iou
                    melhor_id = vid

            if melhor_id is None:
                melhor_id = self.proximo_id
                self.veiculos[melhor_id] = []
                self.proximo_id += 1

            self.veiculos[melhor_id].append((agora, bbox))
            ids_usados.add(melhor_id)

            historico = self.veiculos[melhor_id]
            aproximando = False
            parado = False
            taxa = 0.0

            if len(historico) >= 4:
                t0, b0 = historico[0]
                t1, b1 = historico[-1]
                dt = t1 - t0
                if dt > 0.3:
                    h0, h1 = b0[3], b1[3]
                    x0 = b0[0] + b0[2] // 2
                    x1 = b1[0] + b1[2] // 2
                    taxa = (h1 - h0) / dt
                    desloc_x = abs(x1 - x0)
                    if abs(taxa) < 15 and desloc_x < 30:
                        parado = True
                    if taxa > 100 and h1 > 120:
                        aproximando = True

            resultados.append({'id': melhor_id, 'bbox': bbox,
                               'aproximando': aproximando, 'parado': parado, 'taxa': taxa})

        self.veiculos = {vid: h for vid, h in self.veiculos.items()
                         if agora - h[-1][0] < self.max_idade}
        return resultados


# ================================================================
# FILTRO
# ================================================================
class FiltroSuavizacao:
    def __init__(self, tamanho=HISTORICO_DECISAO):
        self.historico = deque(maxlen=tamanho)

    def adicionar(self, valor):
        self.historico.append((time.time(), valor))

    def obter_suavizado(self, janela=1.5):
        agora = time.time()
        recentes = [v for t, v in self.historico if agora - t <= janela]
        if not recentes:
            return "AGUARDE"
        return Counter(recentes).most_common(1)[0][0]


# ================================================================
# SEMÁFORO
# ================================================================
class SemaforoState:
    def __init__(self):
        self.ultima_cor = None
        self.ultima_observacao = time.time()
        self.historico_cores = deque(maxlen=30)

    def atualizar(self, cor):
        self.historico_cores.append(cor)
        self.ultima_cor = cor
        self.ultima_observacao = time.time()

    def cor_mais_frequente_recente(self, n=8):
        recentes = list(self.historico_cores)[-n:]
        if not recentes:
            return 'desconhecido'
        return Counter(recentes).most_common(1)[0][0]


# ================================================================
# TRÂNSITO
# ================================================================
class TransitoTracker:
    def __init__(self, max_historico=60):
        self.historico = deque(maxlen=max_historico)
        self.largura_frame = 640

    def atualizar(self, veiculos, largura):
        self.largura_frame = largura
        self.historico.append((time.time(), veiculos))

    def veiculos_na_janela(self, segundos=1.5):
        agora = time.time()
        todos = []
        for ts, dets in self.historico:
            if agora - ts <= segundos:
                todos.extend(dets)
        return todos

    def analisar_direcoes(self, distancia_maxima=DISTANCIA_PERIGO):
        veiculos = self.veiculos_na_janela(segundos=1.5)
        largura = self.largura_frame
        zonas = {'esquerda': 0, 'centro': 0, 'direita': 0}
        for v in veiculos:
            cx, cy, area, distancia = v[0], v[1], v[2], v[3]
            if distancia > distancia_maxima:
                continue
            if cx < largura * 0.33:
                zonas['esquerda'] += 1
            elif cx > largura * 0.66:
                zonas['direita'] += 1
            else:
                zonas['centro'] += 1
        return zonas


# ================================================================
# FALA
# ================================================================
class GerenciadorFala:
    def __init__(self, rate=VOZ_RATE, volume=VOZ_VOLUME):
        self.fila = queue.PriorityQueue()
        self.contador = 0
        self.ultima_fala = ""
        self.ultimo_tempo_fala = 0.0
        self.intervalo_minimo = INTERVALO_FALA_MIN
        self.lock = threading.Lock()
        self.rodando = True
        self.rate = rate
        self.volume = volume

        self.prioridades = {
            "ESPERE": 3, "ATRAVESSE COM ATENCAO": 3, "ATRAVESSE COM PRESSA": 3,
            "ESPERE, SINAL VAI FECHAR": 3, "PARE": 3,
            "PODE ATRAVESSAR": 2, "VERIFIQUE E ATRAVESSE": 2,
            "AGUARDE": 1, "OLHE PARA A ESQUERDA": 2, "OLHE PARA A DIREITA": 2,
            "OLHE PARA OS DOIS LADOS": 3,
        }
        self.ultimo_contexto = {}
        self.intervalo_contexto = INTERVALO_CONTEXTO

        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def _criar_speaker(self):
        sp = win32com.client.Dispatch("SAPI.SpVoice")
        sp.Rate = self.rate
        sp.Volume = self.volume
        return sp

    def _worker(self):
        speaker = None
        try:
            speaker = self._criar_speaker()
            print("🔊 SAPI5 pronto")
        except Exception as e:
            print(f"⚠️ Erro SAPI: {e}")

        while self.rodando:
            try:
                _, _, texto = self.fila.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if speaker is None:
                    speaker = self._criar_speaker()
                speaker.Speak(texto)
                print(f"🔊 {texto}")
            except Exception:
                try:
                    speaker = self._criar_speaker()
                    speaker.Speak(texto)
                except Exception:
                    speaker = None

    def _pode_falar(self, texto, prioridade):
        agora = time.time()
        if texto == self.ultima_fala:
            return False
        if agora - self.ultimo_tempo_fala < self.intervalo_minimo:
            if prioridade < 3:
                return False
        return True

    def falar(self, texto, prioridade=None):
        if prioridade is None:
            prioridade = self.prioridades.get(texto, 1)
        if not self._pode_falar(texto, prioridade):
            return False
        with self.lock:
            self.contador += 1
            self.fila.put((3 - prioridade, self.contador, texto))
            self.ultima_fala = texto
            self.ultimo_tempo_fala = time.time()
        return True

    def falar_contexto(self, chave, texto, prioridade=2):
        agora = time.time()
        if agora - self.ultimo_contexto.get(chave, 0) < self.intervalo_contexto:
            return False
        if self.falar(texto, prioridade):
            self.ultimo_contexto[chave] = agora
            return True
        return False

    def encerrar(self):
        self.rodando = False
        self.thread.join(timeout=2.0)


# ================================================================
# VISÃO
# ================================================================
def detectar_cor_semaforo(roi, limiares):
    if roi.size == 0:
        return 'desconhecido'
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask_verde = cv2.inRange(hsv, limiares['verde_min'], limiares['verde_max'])
    m1 = cv2.inRange(hsv, np.array([0, 60, 40]), np.array([10, 255, 255]))
    m2 = cv2.inRange(hsv, np.array([170, 60, 40]), np.array([180, 255, 255]))
    mask_verm = cv2.bitwise_or(m1, m2)
    mask_ama = cv2.inRange(hsv, np.array([15, 90, 90]), np.array([35, 255, 255]))

    v = cv2.countNonZero(mask_verde)
    r = cv2.countNonZero(mask_verm)
    a = cv2.countNonZero(mask_ama)
    mx = max(v, r, a)
    if mx < 10:
        return 'desconhecido'
    if mx == v: return 'verde'
    if mx == r: return 'vermelho'
    return 'amarelo'


def classificar_semaforo(x, y, w, h, altura_frame):
    ar = w / float(h) if h > 0 else 1.0
    pos = y / altura_frame if altura_frame > 0 else 0
    if ar < 0.55 and pos > 0.15:
        return 'pedestre'
    elif ar > 1.0:
        return 'carro'
    return 'indefinido'


def detectar_faixa_robusta(frame, altura, largura, limiares):
    y_ini = int(altura * 0.30)
    roi = frame[y_ini:altura, 0:largura]
    if roi.size == 0:
        return False, [], np.zeros((10, 10), dtype=np.uint8)

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    lower = np.array([0, 0, limiares['branco_min'][2] - 30])
    upper = np.array([180, 90, 255])
    mask_w = cv2.inRange(hsv, lower, upper)
    k = np.ones((7, 7), np.uint8)
    mask_w = cv2.morphologyEx(mask_w, cv2.MORPH_CLOSE, k)
    mask_w = cv2.morphologyEx(mask_w, cv2.MORPH_OPEN, k)

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))

    mask = cv2.bitwise_or(mask_w, edges)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    count = 0
    bboxes = []
    for cnt in contours:
        if cv2.contourArea(cnt) > 300:
            x, y, w, h = cv2.boundingRect(cnt)
            if h == 0:
                continue
            ar = w / float(h)
            if 0.8 < ar < 15:
                count += 1
                bboxes.append((x, y, w, h, cv2.contourArea(cnt)))

    if count >= 2:
        return True, bboxes, mask
    if count == 1:
        x, y, w, h, area = bboxes[0]
        if w > largura * 0.3 and area > 3000:
            return True, bboxes, mask
    return False, bboxes, mask


# ================================================================
# DECISÃO
# ================================================================
def gerar_decisao(transito, semaforo, faixa, carro_prox_mov, aproximando):
    zonas = transito.analisar_direcoes()
    cor = semaforo.cor_mais_frequente_recente(n=8)

    if carro_prox_mov:
        return ("ESPERE", None, 3)
    if aproximando:
        return ("ESPERE", "Veículo se aproximando", 3)

    if cor == 'vermelho':
        if faixa:
            if zonas['centro'] > 0:
                return ("ESPERE", "Veículo sobre a faixa", 3)
            return ("PODE ATRAVESSAR", "Sinal vermelho, pode atravessar", 2)
        return ("AGUARDE", "Aponte para a faixa de pedestres", 1)

    if cor == 'verde':
        if zonas['esquerda'] > 0 and zonas['direita'] > 0:
            return ("ESPERE", "Veículos nos dois lados", 3)
        if zonas['esquerda'] > 0:
            return ("ESPERE", "Veículo à esquerda", 2)
        if zonas['direita'] > 0:
            return ("ESPERE", "Veículo à direita", 2)
        if zonas['centro'] > 0:
            return ("ESPERE", "Veículo à frente", 3)
        return ("AGUARDE", "Aguarde o sinal fechar", 2)

    if cor == 'amarelo':
        return ("ESPERE", "Sinal amarelo, aguarde", 3)

    if faixa:
        total = zonas['esquerda'] + zonas['centro'] + zonas['direita']
        if total == 0:
            return ("PODE ATRAVESSAR", "Rua livre, pode atravessar", 2)
        if zonas['centro'] > 0:
            return ("ESPERE", "Veículo na faixa", 3)
        if zonas['esquerda'] > 0 and zonas['direita'] > 0:
            return ("ESPERE", "Olhe para os dois lados", 3)
        if zonas['esquerda'] > 0:
            return ("ESPERE", "Olhe para a esquerda", 2)
        if zonas['direita'] > 0:
            return ("ESPERE", "Olhe para a direita", 2)
        return ("VERIFIQUE E ATRAVESSE", "Verifique e atravesse", 2)

    return ("AGUARDE", "Aponte para faixa ou semáforo", 1)


# ================================================================
# INICIALIZAÇÃO
# ================================================================
print("🔄 Carregando YOLOv4...")
net = cv2.dnn.readNet("yolov4.weights", "yolov4.cfg")

with open("coco.names", "r") as f:
    classes = [line.strip() for line in f.readlines()]

layer_names = net.getLayerNames()
output_layers = [layer_names[i - 1] for i in net.getUnconnectedOutLayers()]

print("📷 Abrindo câmera...")
camera = cv2.VideoCapture(0)
if not camera.isOpened():
    print("❌ Câmera não disponível.")
    exit()

semaforo_state = SemaforoState()
transito_tracker = TransitoTracker()
rastreador = RastreadorVeiculos()
filtro = FiltroSuavizacao()
falador = GerenciadorFala()
logger = LoggerCSV()

ultima_cor_falada = None
ultimo_carro_falado = 0.0
ultima_orientacao_falada = None
ultima_mensagem_base = None
modo_atual = None

frame_count = 0
fps_contador = deque(maxlen=30)

print("✅ Sistema pronto! ESC para sair.\n")


# ================================================================
# LOOP
# ================================================================
while True:
    ret, frame = camera.read()
    if not ret:
        break

    frame_count += 1
    height, width, _ = frame.shape

    # FPS
    agora = time.time()
    fps_contador.append(agora)
    fps_atual = (len(fps_contador) - 1) / (fps_contador[-1] - fps_contador[0]) if len(fps_contador) >= 2 else 0.0

    # Iluminação
    modo, brilho = detectar_luminosidade(frame)
    if modo != modo_atual:
        modo_atual = modo
    limiares = ajustar_limiares(modo)

    carro_detectado = False
    carro_proximo = False
    carro_proximo_movimento = False
    faixa_detectada = False
    traffic_box = None
    traffic_tipo = None
    aproximando_alerta = False
    carros_parados_count = 0

    # YOLO
    blob = cv2.dnn.blobFromImage(frame, 1 / 255.0, (416, 416), swapRB=True, crop=False)
    net.setInput(blob)
    outputs = net.forward(output_layers)

    boxes, confidences, class_ids = [], [], []
    for output in outputs:
        for det in output:
            scores = det[5:]
            cid = np.argmax(scores)
            conf = scores[cid]
            if conf > 0.5:
                cx, cy = int(det[0] * width), int(det[1] * height)
                w, h = int(det[2] * width), int(det[3] * height)
                x, y = int(cx - w / 2), int(cy - h / 2)
                boxes.append([x, y, w, h])
                confidences.append(float(conf))
                class_ids.append(cid)

    indexes = cv2.dnn.NMSBoxes(boxes, confidences, 0.5, 0.4)

    veiculos_det = []
    veiculos_dist = []

    for i in range(len(boxes)):
        if i not in indexes:
            continue
        x, y, w, h = boxes[i]
        label = classes[class_ids[i]]

        if label in ["car", "bus", "truck", "motorbike"] and w * h > AREA_MINIMA_VEICULO:
            carro_detectado = True
            dist = estimar_distancia(h, label)
            veiculos_det.append((x, y, w, h))
            veiculos_dist.append((x + w // 2, y + h // 2, w * h, dist))
            if dist < DISTANCIA_PERIGO:
                carro_proximo = True
            cor = (0, 0, 255) if dist < DISTANCIA_PERIGO else (0, 255, 0)
            cv2.rectangle(frame, (x, y), (x + w, y + h), cor, 2)
            cv2.putText(frame, f"{label} {dist:.1f}m", (x, y - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, cor, 2)

        if label == "traffic light":
            if h < 250 and y < height * 0.85:
                traffic_box = (x, y, w, h)
                traffic_tipo = classificar_semaforo(x, y, w, h, height)
                cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 0, 0), 2)

    # Rastreio
    resultados = rastreador.atualizar(veiculos_det)
    for r in resultados:
        x, y, w, h = r['bbox']
        if r['parado']:
            carros_parados_count += 1
        elif r['aproximando']:
            aproximando_alerta = True
        dist = estimar_distancia(h)
        if dist < DISTANCIA_MUITO_PROXIMA and not r['parado']:
            carro_proximo_movimento = True

    transito_tracker.atualizar(veiculos_dist, width)

    # Semáforo
    if traffic_box:
        x, y, w, h = traffic_box
        roi = frame[max(0, y):y + h, max(0, x):x + w]
        cor = detectar_cor_semaforo(roi, limiares)
        semaforo_state.atualizar(cor)
    else:
        semaforo_state.atualizar('desconhecido')

    # Faixa
    faixa_detectada, bboxes_faixa, mask_white = detectar_faixa_robusta(frame, height, width, limiares)
    y_off = int(height * 0.30)
    for item in bboxes_faixa:
        fx, fy, fw, fh = item[0], item[1], item[2], item[3]
        cv2.rectangle(frame, (fx, fy + y_off), (fx + fw, fy + fh + y_off), (0, 255, 255), 2)

    # Decisão
    mensagem, orientacao, prioridade = gerar_decisao(
        transito_tracker, semaforo_state, faixa_detectada,
        carro_proximo_movimento, aproximando_alerta
    )
    filtro.adicionar(mensagem)
    mensagem_estavel = filtro.obter_suavizado(janela=1.5)

    # Fala
    falador.falar(mensagem_estavel)
    if mensagem_estavel != ultima_mensagem_base:
        ultima_orientacao_falada = None
        ultima_mensagem_base = mensagem_estavel
    if orientacao and orientacao != ultima_orientacao_falada:
        falador.falar(orientacao, prioridade=prioridade)
        ultima_orientacao_falada = orientacao

    cor_recente = semaforo_state.cor_mais_frequente_recente(n=8)
    if cor_recente != ultima_cor_falada and cor_recente != 'desconhecido':
        if cor_recente == 'verde':
            falador.falar_contexto("sem_verde", "Sinal verde para carros", prioridade=2)
        elif cor_recente == 'vermelho':
            falador.falar_contexto("sem_verm", "Sinal vermelho", prioridade=2)
        elif cor_recente == 'amarelo':
            falador.falar_contexto("sem_ama", "Sinal amarelo, atenção", prioridade=3)
        ultima_cor_falada = cor_recente

    if carro_proximo_movimento and (time.time() - ultimo_carro_falado > 5.0):
        falador.falar_contexto("carro_prox", "Cuidado, veículo próximo", prioridade=3)
        ultimo_carro_falado = time.time()

    # ==================== LOG CSV ====================
    zonas_log = transito_tracker.analisar_direcoes()
    logger.logar({
        'frame': frame_count,
        'fps': fps_atual,
        'modo': modo,
        'brilho': brilho,
        'carro_detectado': carro_detectado,
        'carro_proximo': carro_proximo,
        'aproximando': aproximando_alerta,
        'carros_parados': carros_parados_count,
        'faixa_detectada': faixa_detectada,
        'n_listras': len(bboxes_faixa),
        'semaforo_cor': cor_recente,
        'semaforo_tipo': traffic_tipo or '',
        'zona_esq': zonas_log['esquerda'],
        'zona_cen': zonas_log['centro'],
        'zona_dir': zonas_log['direita'],
        'decisao': mensagem_estavel,
        'orientacao': orientacao or ''
    })

    # HUD mínimo
    cv2.putText(frame, f"FPS: {fps_atual:.1f}", (width - 150, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    cv2.putText(frame, f"Decisao: {mensagem_estavel}", (20, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    cv2.imshow("Tecnologia Assistiva", frame)
    cv2.imshow("Mascara Faixa", mask_white)

    if cv2.waitKey(1) & 0xFF == 27:
        break


# ================================================================
# ENCERRAMENTO
# ================================================================
camera.release()
cv2.destroyAllWindows()
falador.encerrar()
print(f"\n✅ Sessão encerrada. {frame_count} frames processados.")
print(f"📊 CSV salvo em: {ARQUIVO_CSV}")