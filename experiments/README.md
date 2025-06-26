This PR adds an evaluation script that checks if our zero agent correctly finds locations when users ask forest monitoring questions. It includes exported test data, scoring scripts, and performance tracking.

Upload test dataset to your Langfuse instance. see `./upload_dataset.py`
Run the evaluation.

```
$ LANGFUSE_HOST=http://localhost:3000 \
  LANGFUSE_SECRET_KEY=<SECRET_KEY> \
  LANGFUSE_PUBLIC_KEY=<PUBLIC_KEY> \
  python -i experiments/eval_gadm.py
```
