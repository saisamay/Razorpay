import { apiRequest } from './api';
import { Experiment } from '../types/experiments';

export async function getExperiment(experimentId: string, version: string = '1.0'): Promise<Experiment> {
  return apiRequest<Experiment>(`/api/v2/experiments/${experimentId}`, {
    params: { version },
  });
}

export async function getExperimentHistory(experimentId: string): Promise<any[]> {
  return apiRequest<any[]>(`/api/v2/experiments/${experimentId}/history`);
}
