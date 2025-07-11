FROM ubuntu:latest

LABEL maintainer="naveensrinivas282@gmail.com" version="0.0.0" description="This image has the backend for workshop register 2025"

RUN pip install -r requirements.txt

CMD ["clear"]

WORKDIR /root

ENV DATABASE_URI="sqlite//"

ENTRYPOINT ["python3","app.py"]