import cv2
import numpy as np
import pyttsx3

# ---------------- AUDIO ----------------
engine = pyttsx3.init()
engine.setProperty("rate", 170)

ultima_fala = ""

def falar(texto):
    global ultima_fala

    if texto != ultima_fala:
        engine.say(texto)
        engine.runAndWait()
        ultima_fala = texto


# ---------------- YOLO ----------------
net = cv2.dnn.readNet("yolov4.weights", "yolov4.cfg")

with open("coco.names", "r") as f:
    classes = [line.strip() for line in f.readlines()]

layer_names = net.getLayerNames()
output_layers = [layer_names[i - 1] for i in net.getUnconnectedOutLayers()]

camera = cv2.VideoCapture(0)

historico = []

while True:
    ret, frame = camera.read()
    if not ret:
        break

    height, width, channels = frame.shape

    carro_detectado = False
    carro_proximo = False
    faixa_detectada = False
    semaforo_verde = False
    traffic_box = None

    # ---------------- YOLO ----------------
    blob = cv2.dnn.blobFromImage(
        frame,
        1 / 255.0,
        (416, 416),
        swapRB=True,
        crop=False
    )

    net.setInput(blob)
    outputs = net.forward(output_layers)

    boxes = []
    confidences = []
    class_ids = []

    for output in outputs:
        for detection in output:
            scores = detection[5:]
            class_id = np.argmax(scores)
            confidence = scores[class_id]

            if confidence > 0.5:
                center_x = int(detection[0] * width)
                center_y = int(detection[1] * height)

                w = int(detection[2] * width)
                h = int(detection[3] * height)

                x = int(center_x - w / 2)
                y = int(center_y - h / 2)

                boxes.append([x, y, w, h])
                confidences.append(float(confidence))
                class_ids.append(class_id)

    indexes = cv2.dnn.NMSBoxes(boxes, confidences, 0.5, 0.4)

    for i in range(len(boxes)):
        if i in indexes:
            x, y, w, h = boxes[i]
            label = classes[class_ids[i]]

            # veículos
            if label in ["car", "bus", "truck", "motorbike"]:
                carro_detectado = True
                area = w * h

                if area > 30000:
                    carro_proximo = True
                    color = (0, 0, 255)
                else:
                    color = (0, 255, 0)

                cv2.rectangle(frame, (x, y), (x+w, y+h), color, 2)

            # semaforo
            if label == "traffic light":
                if h < 150 and y < height * 0.6:
                    traffic_box = (x, y, w, h)

                    cv2.rectangle(
                        frame,
                        (x, y),
                        (x+w, y+h),
                        (255, 0, 0),
                        2
                    )

    # ---------------- COR VERDE ----------------
    if traffic_box:
        x, y, w, h = traffic_box

        roi = frame[max(0, y):y+h, max(0, x):x+w]

        if roi.size > 0:
            hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

            lower_green = np.array([40, 50, 50])
            upper_green = np.array([90, 255, 255])

            mask_green = cv2.inRange(hsv_roi, lower_green, upper_green)

            if cv2.countNonZero(mask_green) > 20:
                semaforo_verde = True

    # ---------------- FAIXA ----------------
    roi_faixa = frame[int(height * 0.5):height, 0:width]

    hsv = cv2.cvtColor(roi_faixa, cv2.COLOR_BGR2HSV)

    lower_white = np.array([0, 0, 180])
    upper_white = np.array([180, 50, 255])

    mask_white = cv2.inRange(hsv, lower_white, upper_white)

    kernel = np.ones((5, 5), np.uint8)

    mask_white = cv2.morphologyEx(mask_white, cv2.MORPH_OPEN, kernel)
    mask_white = cv2.morphologyEx(mask_white, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(
        mask_white,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    rect_count = 0

    for cnt in contours:
        area = cv2.contourArea(cnt)

        if area > 1000:
            x, y, w, h = cv2.boundingRect(cnt)
            aspect_ratio = w / float(h)

            if 1.5 < aspect_ratio < 8:
                rect_count += 1
                cv2.rectangle(
                    roi_faixa,
                    (x, y),
                    (x+w, y+h),
                    (0, 255, 255),
                    2
                )

    if rect_count >= 3:
        faixa_detectada = True

    # ---------------- DECISAO BRUTA ----------------
    mensagem = "AGUARDE"

    if carro_proximo:
        mensagem = "ESPERE"

    elif semaforo_verde and faixa_detectada and not carro_proximo:
        mensagem = "PODE ATRAVESSAR"

    # ---------------- ESTABILIZACAO ----------------
    historico.append(mensagem)

    if len(historico) > 15:
        historico.pop(0)

    mensagem_estavel = max(set(historico), key=historico.count)

    # ---------------- AUDIO ----------------
    falar(mensagem_estavel)

    # ---------------- HUD ----------------
    overlay = frame.copy()
    cv2.rectangle(overlay, (10, 10), (430, 230), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    cv2.putText(
        frame,
        "TECNOLOGIA ASSISTIVA",
        (20, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 255),
        2
    )

    infos = [
        f"Veiculo detectado: {carro_detectado}",
        f"Veiculo proximo: {carro_proximo}",
        f"Faixa: {faixa_detectada}",
        f"Semaforo verde: {semaforo_verde}",
        f"Decisao: {mensagem_estavel}"
    ]

    y = 75
    for info in infos:
        cv2.putText(
            frame,
            info,
            (20, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2
        )
        y += 30

    cv2.imshow("Tecnologia Assistiva", frame)
    cv2.imshow("Mascara Faixa", mask_white)

    if cv2.waitKey(1) == 27:
        break

camera.release()
cv2.destroyAllWindows()