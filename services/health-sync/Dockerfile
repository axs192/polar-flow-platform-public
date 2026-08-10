FROM public.ecr.aws/lambda/python:3.12 AS builder

RUN pip install --no-cache-dir uv

WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --format requirements.txt -o requirements.txt && \
    uv pip install --system --no-cache -r requirements.txt --target /packages

FROM public.ecr.aws/lambda/python:3.12

COPY --from=builder /packages ${LAMBDA_TASK_ROOT}
COPY src/ ${LAMBDA_TASK_ROOT}/src/

CMD [ "src.app.main.lambda_handler" ]
