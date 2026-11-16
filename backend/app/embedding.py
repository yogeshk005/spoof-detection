from functools import lru_cache


class EmbeddingUnavailable(RuntimeError):
    pass


class FaceEmbedding:
    def __init__(self):
        try:
            import cv2
            import numpy as np
            from insightface.app import FaceAnalysis
        except ImportError as exc:
            raise EmbeddingUnavailable("InsightFace is not installed.") from exc
        self.cv2 = cv2
        self.np = np
        self.app = FaceAnalysis(name="buffalo_s", providers=["CPUExecutionProvider"])
        self.app.prepare(ctx_id=0, det_size=(320, 320))

    def encode(self, image_bytes: bytes) -> list[float]:
        image = self.cv2.imdecode(self.np.frombuffer(image_bytes, dtype=self.np.uint8), self.cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("The uploaded image is not a valid image.")
        faces = self.app.get(image)
        if not faces:
            raise ValueError("No face was detected in the preview image.")
        face = max(faces, key=lambda item: (item.bbox[2] - item.bbox[0]) * (item.bbox[3] - item.bbox[1]))
        vector = self.np.asarray(face.embedding, dtype=self.np.float32)
        norm = self.np.linalg.norm(vector)
        if norm == 0:
            raise ValueError("The face embedding could not be generated.")
        return (vector / norm).astype(float).tolist()

    @staticmethod
    def similarity(left: list[float], right: list[float]) -> float:
        import numpy as np
        return float(np.clip(np.dot(np.asarray(left), np.asarray(right)) * 100, 0, 100))


@lru_cache(maxsize=1)
def get_face_embedding() -> FaceEmbedding:
    return FaceEmbedding()
