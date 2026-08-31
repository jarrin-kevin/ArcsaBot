# Vertex AI Vector Search over Pinecone

We chose a managed vector store and considered Pinecone, but picked Vertex AI Vector Search instead: the project already uses Google GenAI (Gemini) for the LLM and embeddings, and Firebase for the frontend, so staying on Google avoids a third vendor relationship, billing account, and console for a solo-maintained project. LlamaIndex has native support for both, so the swap cost if this turns out wrong is mainly data migration, not code.
