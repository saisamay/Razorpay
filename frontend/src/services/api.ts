const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export interface RequestOptions extends RequestInit {
  merchantId?: string;
  internalToken?: string;
  params?: Record<string, string | number | boolean | undefined | null>;
}

export class ApiError extends Error {
  status: number;
  data: any;

  constructor(status: number, message: string, data?: any) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

export async function apiRequest<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  const { merchantId, internalToken, params, headers: customHeaders, ...restOptions } = options;

  let url = `${API_BASE_URL}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;

  if (params) {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        searchParams.append(key, String(value));
      }
    });
    const queryString = searchParams.toString();
    if (queryString) {
      url += `?${queryString}`;
    }
  }

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(customHeaders as Record<string, string>),
  };

  if (merchantId) {
    headers['X-Merchant-Id'] = merchantId;
  }

  if (internalToken) {
    headers['X-Internal-Token'] = internalToken;
  }

  const response = await fetch(url, {
    ...restOptions,
    headers,
  });

  if (!response.ok) {
    let errorData: any;
    try {
      errorData = await response.json();
    } catch {
      errorData = await response.text();
    }
    const message = (typeof errorData === 'object' && errorData?.detail) 
      ? (typeof errorData.detail === 'string' ? errorData.detail : JSON.stringify(errorData.detail))
      : `API Error ${response.status}: ${response.statusText}`;
      
    throw new ApiError(response.status, message, errorData);
  }

  return response.json() as Promise<T>;
}
