# CI smoke-test artifact, NOT the production deployment path.
#
# Inside a container, systemctl/journalctl/ss and host-scope process and disk
# views describe the namespace rather than the machine, so the report would be
# about the container. What this image is good for is exercising the
# graceful-degradation paths in CI. Production runs on the host under a systemd
# timer; see systemd/README.md.
FROM python:3.12-slim
WORKDIR /app
# The agent needs no packages at runtime; it reads /proc and /sys and shells out
# to core utilities. Nothing is installed here on purpose.
COPY . .
ENV PYTHONPATH=/app
RUN useradd -m appuser
USER appuser
ENTRYPOINT ["python", "-u", "-m", "agent.monitor"]
