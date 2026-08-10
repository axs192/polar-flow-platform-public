FROM public.ecr.aws/lambda/python:3.12 AS builder

RUN pip install --no-cache-dir uv

WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --format requirements.txt -o requirements.txt && \
    uv pip install --system --no-cache -r requirements.txt --target /packages

FROM public.ecr.aws/lambda/python:3.12

COPY --from=builder /packages ${LAMBDA_TASK_ROOT}
COPY exercise_insights/ ${LAMBDA_TASK_ROOT}/exercise_insights/

CMD [ "exercise_insights.whatsapp_adapter.lambda_handler.lambda_handler" ]
