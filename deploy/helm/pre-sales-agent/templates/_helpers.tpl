{{- define "psa.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "psa.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else if contains (include "psa.name" .) .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "psa.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "psa.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "psa.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: pre-sales-agent
{{- end -}}

{{/* Selector labels for one component: include "psa.selector" (list $ "api") */}}
{{- define "psa.selector" -}}
{{- $ := index . 0 -}}
app.kubernetes.io/name: {{ include "psa.name" $ }}
app.kubernetes.io/instance: {{ $.Release.Name }}
app.kubernetes.io/component: {{ index . 1 }}
{{- end -}}

{{/* Image reference: include "psa.image" (list $ .Values.api.image) */}}
{{- define "psa.image" -}}
{{- $ := index . 0 -}}
{{- $img := index . 1 -}}
{{- printf "%s:%s" $img.repository (default $.Chart.AppVersion $img.tag) -}}
{{- end -}}

{{- define "psa.filesClaim" -}}
{{- default (printf "%s-files" (include "psa.fullname" .)) .Values.files.existingClaim -}}
{{- end -}}

{{/* Database URL env vars from a credentials secret: include "psa.dbEnv" (list $ "PSA_DATABASE_URL" secretName) */}}
{{- define "psa.dbEnv" -}}
{{- $ := index . 0 -}}
{{- $var := index . 1 -}}
{{- $secret := index . 2 -}}
{{- $prefix := $var | replace "_URL" "" -}}
- name: {{ $prefix }}_USER
  valueFrom:
    secretKeyRef: { name: {{ $secret }}, key: username }
- name: {{ $prefix }}_PASSWORD
  valueFrom:
    secretKeyRef: { name: {{ $secret }}, key: password }
- name: {{ $var }}
  value: {{ printf "postgresql+psycopg://$(%s_USER):$(%s_PASSWORD)@%s:%v/%s" $prefix $prefix $.Values.database.host $.Values.database.port $.Values.database.name | quote }}
{{- end -}}

{{- define "psa.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: {{ .runAsUser }}
runAsGroup: {{ .runAsGroup }}
fsGroup: {{ .fsGroup }}
fsGroupChangePolicy: OnRootMismatch
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "psa.containerSecurityContext" -}}
allowPrivilegeEscalation: false
capabilities:
  drop: [ALL]
{{- end -}}

{{/* Env shared by api and worker: settings ConfigMap, backend secret, database URL. */}}
{{- define "psa.backendEnvFrom" -}}
- configMapRef:
    name: {{ include "psa.fullname" . }}-backend
- secretRef:
    name: {{ .Values.backendSecret }}
    optional: true
{{- /* Provider-issued settings (e.g. PSA_AUTH0_AUDIENCE, which Zitadel generates). */}}
{{- with .Values.auth.backendSecret }}
- secretRef:
    name: {{ . }}
    optional: true
{{- end }}
{{- end -}}
