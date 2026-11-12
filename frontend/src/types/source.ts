export interface DataSource {
  id: number
  code: string
  name: string
  protocol: 'opcua' | 'dcs' | 'csv'
  sample_interval_s: number
  timezone: string
  drift_hint_ms: number
  status: string
  workshop: string
  description: string
  last_capture_at?: string | null
}

export interface Signal {
  id: number
  code: string
  source_id: number
  device_code: string
  device_name: string
  measure_name: string
  tag_path: string
  unit: string
  sampling_interval_s: number
  is_active: boolean
  scale_min?: number
  scale_max?: number
}

export interface SourceDetail {
  source: DataSource
  signals: Signal[]
  raw_point_count: number
  signal_count: number
}

export interface OwnershipSegment {
  id: number
  signal_id: number
  kind: 'baseline' | 'reassignment'
  device_code: string
  device_name: string
  effective_from: string
  effective_to: string | null
  note: string
  sample_count: number
  created_by_name: string | null
  created_at: string | null
}

export interface OwnershipTimeline {
  signal: Signal
  current: { device_code: string; device_name: string }
  segments: OwnershipSegment[]
}

export interface ReassignResult {
  segment: OwnershipSegment
  closed_segment: OwnershipSegment | null
  affected_samples: number
  signal: Signal
}
