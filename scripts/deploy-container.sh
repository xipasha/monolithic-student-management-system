#!/usr/bin/env bash
set -euo pipefail

readonly RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-work}"
readonly WEBAPP_NAME="${AZURE_WEBAPP_NAME:-sms-student-management-20261103}"
readonly IMAGE_REPOSITORY="ghcr.io/xipasha/monolithic-student-management-system"
readonly REGISTRY_URL="https://ghcr.io"

usage() {
    echo "Usage: $0 <40-character-image-sha> [port] | --restore <linuxFxVersion>" >&2
    exit 2
}

if [[ $# -lt 1 ]]; then
    usage
fi

secret_key="$(
    az webapp config appsettings list \
        --name "$WEBAPP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query "[?name=='SECRET_KEY'].value | [0]" \
        --output tsv
)"
if [[ -z "$secret_key" || "$secret_key" == "None" ]]; then
    echo "The target App Service has no SECRET_KEY setting; refusing to deploy." >&2
    exit 1
fi
unset secret_key

configure_app_service() {
    local port="$1"
    local health_config
    health_config="$(mktemp)"
    printf '{"healthCheckPath":"/health"}\n' > "$health_config"

    az webapp config appsettings set \
        --name "$WEBAPP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --settings "WEBSITES_PORT=$port" PORT=8000 \
        --output none

    az webapp config set \
        --name "$WEBAPP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --generic-configurations "@$health_config" \
        --output none

    rm -f -- "$health_config"
}

case "$1" in
    --restore)
        [[ $# -eq 2 ]] || usage
        previous_runtime="$2"
        port=8000
        if [[ "$previous_runtime" == "DOCKER|${IMAGE_REPOSITORY}:"* ]]; then
            image_sha="${previous_runtime##*:}"
            if [[ ! "$image_sha" =~ ^[[:xdigit:]]{40}$ ]]; then
                echo "Unsupported previous image reference: $previous_runtime" >&2
                exit 2
            fi
            az webapp config container set \
                --name "$WEBAPP_NAME" \
                --resource-group "$RESOURCE_GROUP" \
                --container-image-name "${IMAGE_REPOSITORY}:${image_sha}" \
                --container-registry-url "$REGISTRY_URL" \
                --output none
        elif [[ "$previous_runtime" == "PYTHON|"* ]]; then
            az webapp config set \
                --name "$WEBAPP_NAME" \
                --resource-group "$RESOURCE_GROUP" \
                --linux-fx-version "$previous_runtime" \
                --output none
        else
            echo "Unsupported previous App Service runtime: $previous_runtime" >&2
            exit 2
        fi
        ;;
    *)
        [[ $# -ge 1 && $# -le 2 ]] || usage
        image_sha="$1"
        port="${2:-8000}"
        if [[ ! "$image_sha" =~ ^[[:xdigit:]]{40}$ ]]; then
            echo "Image SHA must be exactly 40 hexadecimal characters." >&2
            exit 2
        fi
        if [[ ! "$port" =~ ^[0-9]{1,5}$ ]] || (( port < 1 || port > 65535 )); then
            echo "Port must be an integer between 1 and 65535." >&2
            exit 2
        fi
        image_sha="${image_sha,,}"
        az webapp config container set \
            --name "$WEBAPP_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --container-image-name "${IMAGE_REPOSITORY}:${image_sha}" \
            --container-registry-url "$REGISTRY_URL" \
            --output none
        ;;
esac

configure_app_service "$port"
