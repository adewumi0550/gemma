FROM ollama/ollama:latest
ARG MODEL=gemma4
ENV OLLAMA_HOST=0.0.0.0:8080 \
    OLLAMA_MODELS=/models \
    OLLAMA_KEEP_ALIVE=-1 \
    OLLAMA_NUM_PARALLEL=1
RUN /bin/ollama serve & \
    pid=$! ; \
    until /bin/ollama list >/dev/null 2>&1 ; do sleep 1 ; done ; \
    /bin/ollama pull "${MODEL}" ; \
    /bin/ollama list ; \
    kill $pid
ENTRYPOINT []
CMD ["/bin/ollama", "serve"]
