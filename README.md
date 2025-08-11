# create-ynab-transaction

Run function locally:

```sh
functions_framework --target process_request --debug
```

Test using curl:

```sh
curl localhost:8080 \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{
        "amount":"$6.22",
        "name":"Key Food",
        "card":"Apple Card",
        "merchant":"Key Food",
        "date":"2025-08-09T21:26:45-04:00"
      }'
```

Setup gcp auth:

```
gcloud auth application-default login
gcloud auth application-default set-quota-project <project-id>
```