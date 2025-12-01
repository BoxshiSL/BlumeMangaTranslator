"""Project-level utilities (image loading, conversions)."""
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


def load_image_as_np(file_path: Path) -> np.ndarray:
    """
    Загружает изображение страницы из файла в виде numpy-массива.

    :param file_path: Путь к файлу изображения.
    :return: Изображение как np.ndarray (формат BGR, как в OpenCV).
    :raises FileNotFoundError: если файл не существует.
    :raises ValueError: если изображение не удалось загрузить или формат некорректен.
    """
    if not file_path.is_file():
        raise FileNotFoundError(f"Image file not found: {file_path}")

    image = cv2.imread(str(file_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Failed to load image from: {file_path}")

    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("Loaded image is not a 3-channel BGR image.")

    return image


def bgr_to_rgb(image: np.ndarray) -> np.ndarray:
    """
    Конвертирует изображение из формата BGR (как в OpenCV) в RGB.

    :param image: Входное изображение BGR.
    :return: Изображение в формате RGB.
    :raises TypeError: если image не является numpy.ndarray.
    """
    if not isinstance(image, np.ndarray):
        raise TypeError("image must be a numpy.ndarray")
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
