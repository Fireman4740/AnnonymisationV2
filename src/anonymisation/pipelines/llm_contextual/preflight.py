"""Sanité synthétique suivie dans le même run, avant toute campagne coûteuse."""

import json

from anonymisation.pipelines.llm_contextual.system import LlmContextualSystem
from anonymisation.schema.models import Document, Domain


def main() -> None:
    document = Document(
        doc_id="contextual-preflight",
        dataset="synthetic-preflight",
        split="test",
        domain=Domain.GENERIC,
        language="fr",
        text="Je m'appelle Jeanne Martin. Contactez-moi à jeanne.martin@example.com pour annuler une commande.",
    )
    result = LlmContextualSystem().run(document)
    summary = {
        "system": "llm-contextual-v1",
        "status": result.status,
        "annotations": len(result.annotations),
        "errors": list(result.errors),
    }
    print("CONTEXTUAL_PREFLIGHT", json.dumps(summary, ensure_ascii=False), flush=True)
    if result.status == "error" or "jeanne.martin@example.com" in result.anonymized_text:
        raise RuntimeError("Préflight Qwen local / JSON structuré échoué : campagne non lancée")


if __name__ == "__main__":
    main()
