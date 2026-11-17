{{- define "opt.fullname" -}}
{{- default .Release.Name .Values.fullnameOverride | trunc 50 | trimSuffix "-" -}}
{{- end -}}

{{- define "opt.labels" -}}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: {{ include "opt.fullname" . }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
{{- end -}}

{{/* imagePullSecrets from global (strings or {name:}) plus the chart list, de-duplicated */}}
{{- define "opt.pullSecrets" -}}
{{- $names := list -}}
{{- range (concat (default list .Values.global.imagePullSecrets) (default list .Values.imagePullSecrets)) -}}
{{- $n := "" -}}
{{- if kindIs "map" . -}}{{- $n = .name -}}{{- else -}}{{- $n = . -}}{{- end -}}
{{- if and $n (not (has $n $names)) -}}{{- $names = append $names $n -}}{{- end -}}
{{- end -}}
{{- if $names }}
imagePullSecrets:
{{- range $names }}
  - name: {{ . }}
{{- end }}
{{- end -}}
{{- end -}}

{{- define "opt.pgHost" -}}{{ include "opt.fullname" . }}-postgres{{- end -}}
{{- define "opt.secretName" -}}{{ include "opt.fullname" . }}-db{{- end -}}
