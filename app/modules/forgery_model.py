"""
ARGUS — Forgery Detection Model

EfficientNet-B0 binary classifier used for document forgery detection.

Class mapping:
    0 = Authentic
    1 = Forged

Decision zones:
    forged_probability <= 0.30 -> Authentic
    0.30 < forged_probability < 0.69 -> Uncertain
    forged_probability >= 0.69 -> Forged
"""

from pathlib import Path
from typing import Dict, Union

import torch
import torch.nn as nn
from PIL import Image
from torchvision import transforms
from torchvision.models import efficientnet_b0


# ============================================================
# CONFIGURATION
# ============================================================

DEFAULT_MODEL_PATH = (
    Path(__file__).resolve().parent.parent
    / "models"
    / "argus_efficientnet_b0_corrected_best.pth"
)

FORGED_THRESHOLD = 0.69
AUTHENTIC_THRESHOLD = 0.30

CLASS_NAMES = {
    0: "Authentic",
    1: "Forged",
}


# ============================================================
# PREPROCESSING
# ============================================================

TRANSFORM = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(
        mean=[0.485, 0.456, 0.406],
        std=[0.229, 0.224, 0.225],
    ),
])


# ============================================================
# MODEL
# ============================================================

class ForgeryModel:
    """
    Wrapper around the trained ARGUS EfficientNet-B0 model.
    """

    def __init__(
        self,
        model_path: Union[str, Path] = DEFAULT_MODEL_PATH,
        device: str = None,
    ):
        self.model_path = Path(model_path)

        if device is None:
            self.device = torch.device(
                "cuda" if torch.cuda.is_available() else "cpu"
            )
        else:
            self.device = torch.device(device)

        self.model = self._load_model()

    # --------------------------------------------------------
    # CREATE + LOAD MODEL
    # --------------------------------------------------------

    def _load_model(self) -> nn.Module:
        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"ARGUS forgery model checkpoint not found:\n"
                f"{self.model_path}"
            )

        # Recreate the exact architecture used during training.
        model = efficientnet_b0(weights=None)

        # Original EfficientNet-B0 classifier:
        # Linear(in_features=1280, out_features=1000)
        #
        # ARGUS replaces it with a 2-class classifier.
        in_features = model.classifier[1].in_features

        model.classifier[1] = nn.Linear(
            in_features,
            2,
        )

        # Load the ARGUS checkpoint.
        checkpoint = torch.load(
            self.model_path,
            map_location=self.device,
            weights_only=False,
        )

        # The training pipeline stores the weights under
        # "model_state_dict".
        if "model_state_dict" not in checkpoint:
            raise KeyError(
                "Checkpoint does not contain 'model_state_dict'. "
                "The checkpoint may not be an ARGUS model checkpoint."
            )

        model.load_state_dict(
            checkpoint["model_state_dict"]
        )

        model = model.to(self.device)
        model.eval()

        return model

    # --------------------------------------------------------
    # IMAGE PREPROCESSING
    # --------------------------------------------------------

    def preprocess(
        self,
        image: Image.Image,
    ) -> torch.Tensor:
        """
        Convert a PIL image into the tensor expected by ARGUS.
        """

        if not isinstance(image, Image.Image):
            raise TypeError(
                "image must be a PIL.Image.Image"
            )

        # EfficientNet expects RGB input.
        image = image.convert("RGB")

        tensor = TRANSFORM(image)

        # Add batch dimension.
        tensor = tensor.unsqueeze(0)

        return tensor.to(self.device)

    # --------------------------------------------------------
    # PREDICTION
    # --------------------------------------------------------

    @torch.no_grad()
    def predict(
        self,
        image: Image.Image,
    ) -> Dict[str, Union[str, int, float]]:
        """
        Run forgery detection on a PIL image.

        Returns:
            {
                "label": "Authentic" | "Forged" | "Uncertain",
                "class_id": 0 | 1 | None,
                "authentic_probability": float,
                "forged_probability": float,
            }
        """

        tensor = self.preprocess(image)

        logits = self.model(tensor)

        # Convert the two logits into probabilities.
        probabilities = torch.softmax(
            logits,
            dim=1,
        )[0]

        authentic_probability = float(
            probabilities[0].item()
        )

        forged_probability = float(
            probabilities[1].item()
        )

        # ----------------------------------------------------
        # THREE-ZONE DECISION ENGINE
        # ----------------------------------------------------

        if forged_probability >= FORGED_THRESHOLD:
            label = "Forged"
            class_id = 1

        elif forged_probability <= AUTHENTIC_THRESHOLD:
            label = "Authentic"
            class_id = 0

        else:
            label = "Uncertain"
            class_id = None

        return {
            "label": label,
            "class_id": class_id,
            "authentic_probability": authentic_probability,
            "forged_probability": forged_probability,
        }


# ============================================================
# SINGLETON MODEL INSTANCE
# ============================================================

_model = None


def get_forgery_model() -> ForgeryModel:
    """
    Return the shared ARGUS forgery model.

    The model is loaded only once and reused for subsequent
    predictions. This prevents loading the ~checkpoint repeatedly
    for every request.
    """

    global _model

    if _model is None:
        _model = ForgeryModel()

    return _model


# ============================================================
# CONVENIENCE FUNCTION
# ============================================================

def predict_forgery(
    image: Image.Image,
) -> Dict[str, Union[str, int, float]]:
    """
    Convenience function used by the ARGUS API.
    """

    model = get_forgery_model()

    return model.predict(image)
# Device fallback: Optimized for standard 4-core cloud CPUs without dedicated GPU.
