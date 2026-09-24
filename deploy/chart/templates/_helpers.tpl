{{- define "calibration-drift.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "calibration-drift.labels" -}}
app.kubernetes.io/name: {{ include "calibration-drift.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{- define "calibration-drift.selectorLabels" -}}
app.kubernetes.io/name: {{ include "calibration-drift.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "calibration-drift.mlflowUrl" -}}
http://{{ .Release.Name }}-mlflow:{{ .Values.mlflow.port }}
{{- end -}}
