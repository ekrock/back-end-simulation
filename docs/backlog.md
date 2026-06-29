# Backlog

Future enhancements, not yet scheduled.

---

## Security

**Redis shared storage for rate limiter**
Flask-Limiter currently uses in-memory storage. With 2 gunicorn workers each process tracks its own counter, so a user can make up to 2× the intended limit (10 uploads/hour instead of 5). Adding Redis as a shared backend would make the rate limit precise across all workers. Requires installing Redis on EC2 and adding `flask-limiter[redis]` to requirements.txt.
