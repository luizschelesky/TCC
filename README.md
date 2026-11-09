# 🦯 Tecnologia Assistiva para Travessia de Pedestres

Sistema de tecnologia assistiva baseado em visão computacional para apoio à travessia de pedestres com deficiência visual.

> Trabalho de Conclusão de Curso (TCC) — Bacharelado em Engenharia de Software  
> Universidade Estadual de Ponta Grossa (UEPG) — 2026

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![OpenCV](https://img.shields.io/badge/OpenCV-4.x-green)
![YOLOv4](https://img.shields.io/badge/YOLOv4-Darknet-red)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)

---

## 🚨 ATENÇÃO — ANTES DE EXECUTAR

> ⚠️ **O projeto NÃO funciona sem os arquivos do modelo YOLOv4.**
>
> Por conta do tamanho (~250 MB), esses arquivos **não estão incluídos neste repositório**. Você precisa baixá-los separadamente e colocá-los **na raiz do projeto**, no mesmo diretório do `main.py`.

### Arquivos obrigatórios

| Arquivo | Tamanho aproximado | Onde colocar |
|---------|--------------------|--------------|
| `yolov4.weights` | ~250 MB | Raiz do projeto |
| `yolov4.cfg` | ~10 KB | Raiz do projeto |
| `coco.names` | ~1 KB | Raiz do projeto |

### Estrutura esperada
projeto/
├── main.py
├── yolov4.weights ← obrigatório (~250 MB)
├── yolov4.cfg ← obrigatório
├── coco.names ← obrigatório
└── README.md

> ❗ Se você tentar rodar o `main.py` sem esses arquivos, verá o erro:
> ```
> cv2.error: OpenCV(4.x) ... Can't open file: 'yolov4.weights' in read mode
> ```

---

## 📖 Sobre o projeto

Este repositório contém o protótipo funcional desenvolvido para o TCC. O sistema captura vídeo da câmera, interpreta o ambiente urbano com YOLOv4 e técnicas clássicas de processamento de imagens (OpenCV), aplica uma lógica de decisão e comunica o resultado ao usuário por **síntese de voz**.

Todas as detecções e decisões são registradas em um arquivo CSV para permitir análise quantitativa posterior.

### Componentes principais

- 🔍 Detecção de veículos e semáforos com **YOLOv4 (COCO)**;
- 🦓 Detecção de faixas de pedestres com **HSV + Canny**;
- 📏 Estimativa de distância por **geometria de perspectiva** (altura real por categoria);
- 🧠 **Lógica de decisão** conservadora com estabilização temporal;
- 🔊 **Síntese de voz** via SAPI5 (Windows);
- 📊 **Log em CSV** (`metricas_tcc.csv`) para análise.

---

## 🎯 Funcionalidades

| Funcionalidade | Descrição |
|----------------|-----------|
| Detecção de veículos | Carro, ônibus, caminhão e motocicleta |
| Estimativa de distância | `d = (altura_real × focal) / altura_em_pixels`, por categoria |
| Detecção de semáforo | YOLO localiza + análise de cor em HSV (verde/vermelho/amarelo) |
| Detecção de faixa | Máscara HSV de branco + bordas Canny, combinadas por OR |
| Rastreamento de veículos | IoU entre frames — distingue parado de aproximando |
| Análise de zonas | Veículos classificados em esquerda / centro / direita |
| Lógica de decisão | `PODE ATRAVESSAR`, `ESPERE`, `AGUARDE` |
| Suavização temporal | Moda dos últimos 15 frames (janela de 1,5 s) |
| Alerta sonoro | SAPI5 em thread separada, sem bloquear o loop |
| Log CSV | Gravado a cada 1 segundo |

---

## ⚙️ Requisitos

- **Python 3.9+**
- **Windows** (obrigatório — o código usa `win32com.client` / SAPI5)
- **Webcam** (o código abre `cv2.VideoCapture(0)`)

### Bibliotecas Python

```bash
pip install opencv-python numpy pywin32
