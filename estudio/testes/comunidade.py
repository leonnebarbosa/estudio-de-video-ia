"""Modelos falsos "da comunidade" para os testes.

No estudio de verdade, modelos da comunidade so entram pelo arquivo local, fora do git (extras.py), e o rodar_testes.py
desliga esse arquivo para os testes darem o mesmo resultado em qualquer maquina. Estes dois cobrem os mesmos caminhos
do codigo: um Wan com a aceleracao embutida (sem LoRA, shift 5) e um Krea 2 no seletor do Texto para imagem."""
from texto_para_imagem import MODELOS_TEXTO
from wan_para_video import MODELOS_WAN

WAN = "comunidade"
KREA = "comunidade_krea2"
H3_TURBO = "comunidade_h3_ref2va_v2_pruned_turbo_int8.safetensors"
H3_BASE = "comunidade_h3_ref2va_v2_pruned_int8.safetensors"

MODELOS_WAN.setdefault(WAN, {"nome": "Wan da comunidade", "carregador": "UNETLoader", "shift": 5, "lora": None,
                             "alta": "Comunidade_Wan22_I2V_14B_v1_HIGH_int8.safetensors", "baixa": "Comunidade_Wan22_I2V_14B_v1_LOW_int8.safetensors"})
MODELOS_TEXTO.setdefault(KREA, {"nome": "Krea 2 da comunidade", "familia": "krea2", "ajuda": "Krea 2 de teste.", "carregador": "UNETLoader",
                                "unet": "Comunidade-Krea2-Turbo-v3_int8.safetensors", "encoder": "qwen3vl_4b_fp8_scaled.safetensors", "tipo_encoder": "krea2",
                                "vae": "qwen_image_vae.safetensors", "passos": 8, "amostrador": "euler", "agendador": "linear_quadratic",
                                "latente": "EmptyLatentImage", "negativo": "zero", "shift": None})
