import os

# -----------------------------
# Hugging Face cache / mirror
# -----------------------------
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", "/home/yinzs/models/huggingface")
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", "/home/yinzs/models/huggingface/hub")
os.environ.setdefault("TRANSFORMERS_CACHE", "/home/yinzs/models/huggingface/transformers")
os.environ.setdefault("TORCH_HOME", "/home/yinzs/models/torch")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import torch
import torch_npu

# Very important:
# This monkey-patches CUDA APIs to NPU where possible.
# After importing this, torch.cuda.is_available() may become True on Ascend.
import torch_npu.contrib.transfer_to_npu


# -----------------------------
# Lightning CUDA compatibility patches for Ascend
# -----------------------------
def patch_cuda_capability_for_lightning():
    """
    PyTorch Lightning's CUDA accelerator calls:
        torch.cuda.get_device_capability(device)

    On Ascend with torch_npu.contrib.transfer_to_npu, this may return None because
    torch.npu.get_device_capability is not implemented.

    Lightning only uses this check to decide whether to print/set matmul precision
    hints for Ampere-or-later NVIDIA GPUs. Returning (8, 0) is enough to satisfy
    the expected tuple format.
    """
    def fake_get_device_capability(device=None):
        return (8, 0)

    def fake_get_device_name(device=None):
        try:
            return torch.npu.get_device_name(0)
        except Exception:
            return "Ascend NPU"

    torch.cuda.get_device_capability = fake_get_device_capability
    torch.cuda.get_device_name = fake_get_device_name

    try:
        torch.set_float32_matmul_precision("high")
    except Exception:
        pass


patch_cuda_capability_for_lightning()

from comet import load_from_checkpoint


def main():
    ckpt = "/home/yinzs/models/huggingface/hub/models--Unbabel--XCOMET-XL/snapshots/6a123c5e8e6dccab25e5fcffa3c8b417abadb462/checkpoints/model.ckpt"

    print("=" * 80)
    print("Environment")
    print("=" * 80)
    print("HF_ENDPOINT:", os.environ.get("HF_ENDPOINT"))
    print("HF_HOME:", os.environ.get("HF_HOME"))
    print("HUGGINGFACE_HUB_CACHE:", os.environ.get("HUGGINGFACE_HUB_CACHE"))
    print("TRANSFORMERS_CACHE:", os.environ.get("TRANSFORMERS_CACHE"))

    print("=" * 80)
    print("Torch / NPU")
    print("=" * 80)
    print("torch:", torch.__version__)
    print("torch_npu:", torch_npu.__version__)
    print("torch.cuda.is_available():", torch.cuda.is_available())
    print("torch.cuda.get_device_capability(0):", torch.cuda.get_device_capability(0))
    print("torch.cuda.get_device_name(0):", torch.cuda.get_device_name(0))

    try:
        print("torch.npu.is_available():", torch.npu.is_available())
        print("NPU:", torch.npu.get_device_name(0))
        torch.npu.set_device(0)
    except Exception as e:
        print("NPU check failed:", repr(e))

    print("=" * 80)
    print("Loading XCOMET model")
    print("=" * 80)
    print("checkpoint:", ckpt)

    model = load_from_checkpoint(ckpt)
    model.eval()

    data = [
        {
            "src": "This is a test sentence.",
            "mt": "这是一个测试句子。"
        }
    ]

    print("=" * 80)
    print("Running predict via CUDA-compatible Ascend NPU path")
    print("=" * 80)

    # Important:
    # COMET's predict() checks:
    #   if gpus > 0 and devices is not None:
    #       assert len(devices) == gpus
    #
    # So for gpus=1, devices must be [0], not 1.
    #
    # transfer_to_npu makes CUDA APIs redirect to NPU.
    pred = model.predict(
        data,
        batch_size=1,
        gpus=1,
        devices=[0],
        accelerator="cuda",
        num_workers=0,
        progress_bar=True,
        length_batching=False,
    )

    print("=" * 80)
    print("Prediction result")
    print("=" * 80)
    print("Prediction object:", pred)
    print("Scores:", pred.scores)

    try:
        print("System score:", pred.system_score)
    except Exception:
        pass

    print("=" * 80)
    print("Done")
    print("=" * 80)


if __name__ == "__main__":
    main()