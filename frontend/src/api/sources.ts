import http from './http'
import type { DataSource, OwnershipTimeline, ReassignResult, Signal, SourceDetail } from '../types/source'

export async function fetchSources(): Promise<{ items: DataSource[] }> {
  const { data } = await http.get<{ items: DataSource[] }>('/data-sources')
  return data
}

export async function fetchSourceDetail(sourceId: number): Promise<SourceDetail> {
  const { data } = await http.get<SourceDetail>(`/data-sources/${sourceId}`)
  return data
}

export async function fetchSignals(deviceCode?: string): Promise<{ items: Signal[] }> {
  const { data } = await http.get<{ items: Signal[] }>('/signals', { params: { device_code: deviceCode } })
  return data
}

export async function fetchOwnership(signalId: number): Promise<OwnershipTimeline> {
  const { data } = await http.get<OwnershipTimeline>(`/signals/${signalId}/ownership`)
  return data
}

export interface ReassignPayload {
  device_code: string
  device_name: string
  effective_from: string
  note: string
}

export async function reassignSignal(signalId: number, payload: ReassignPayload): Promise<ReassignResult> {
  const { data } = await http.post<ReassignResult>(`/signals/${signalId}/reassignments`, payload)
  return data
}
