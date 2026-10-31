"""Sanité synthétique locale avant une future campagne, jamais au scoring."""
import json

from anonymisation.pipelines.llm_anchored.system import LlmAnchoredSystem
from anonymisation.schema.models import Document, Domain


def main() -> None:
    text = "Je m'appelle Jeanne Martin. Contactez-moi à jeanne.martin@example.com pour annuler une commande."
    doc = Document(doc_id="anchored-preflight", dataset="synthetic-preflight", split="test",
                   domain=Domain.GENERIC, language="fr", text=text)
    result = LlmAnchoredSystem().run(doc)
    print("ANCHORED_PREFLIGHT", json.dumps({"system":"llm-anchored-v1", "status":result.status,
          "annotations":len(result.annotations), "errors":list(result.errors)}, ensure_ascii=False), flush=True)
    if result.status == "error" or "jeanne.martin@example.com" in result.anonymized_text:
        raise RuntimeError("Préflight Qwen ancré échoué : campagne non lancée")


if __name__ == "__main__":
    main()
