import { useQuery, useSuspenseQuery, useMutation } from "@tanstack/react-query";
import type { UseQueryOptions, UseSuspenseQueryOptions, UseMutationOptions } from "@tanstack/react-query";
export class ApiError extends Error {
    status: number;
    statusText: string;
    body: unknown;
    constructor(status: number, statusText: string, body: unknown){
        super(`HTTP ${status}: ${statusText}`);
        this.name = "ApiError";
        this.status = status;
        this.statusText = statusText;
        this.body = body;
    }
}
export interface AgentTraceStep {
    agent: string;
    latency_ms?: number | null;
    method?: string | null;
    output?: unknown | null;
    reasoning?: string | null;
}
export interface ComplexValue {
    display?: string | null;
    primary?: boolean | null;
    ref?: string | null;
    type?: string | null;
    value?: string | null;
}
export interface Evidence {
    confidence: number;
    field: string;
    snippet: string;
}
export interface FacilityOut {
    address?: string | null;
    city?: string | null;
    confidence?: Record<string, number> | null;
    country?: string;
    equipment?: string[] | null;
    external_id?: string | null;
    id: string;
    latitude?: number | null;
    longitude?: number | null;
    name: string;
    pincode?: string | null;
    procedures?: string[] | null;
    raw_description?: string | null;
    services?: string[] | null;
    source?: string | null;
    specialties?: string[] | null;
    state?: string | null;
    type?: string | null;
}
export interface HTTPValidationError {
    detail?: ValidationError[];
}
export interface LocationIn {
    label?: string | null;
    lat?: number | null;
    lng?: number | null;
}
export interface Name {
    family_name?: string | null;
    given_name?: string | null;
}
export interface ParsedQueryOut {
    capability_text?: string | null;
    language?: string | null;
    location?: Record<string, unknown> | null;
    location_text?: string | null;
    raw_query?: string | null;
    specialty_terms?: string[] | null;
    urgency?: string | null;
}
export interface SearchIn {
    limit?: number;
    location?: LocationIn | null;
    location_text?: string | null;
    min_confidence?: number;
    query?: string | null;
    radius_km?: number;
    specialties?: string[] | null;
}
export interface SearchOrigin {
    label?: string | null;
    lat?: number | null;
    lng?: number | null;
}
export interface SearchResultItem {
    attributes?: Record<string, unknown> | null;
    distance_km?: number | null;
    evidence?: Evidence[] | null;
    evidence_summary?: string | null;
    facility: FacilityOut;
    match_score: number;
    missing_evidence?: string[] | null;
    quality_boost?: number | null;
    quality_reasons?: string[] | null;
    reasoning?: string | null;
    scoring_method?: string | null;
    top_evidence?: Evidence | null;
    trust_rank?: number | null;
    trust_signal?: string | null;
}
export interface SearchResults {
    agent_trace?: AgentTraceStep[];
    mode: string;
    origin: SearchOrigin;
    parsed_query?: ParsedQueryOut | null;
    reasoning_summary?: string | null;
    recommendation_reasoning?: string | null;
    results: SearchResultItem[];
}
export interface SubmissionIn {
    captured_at?: string | null;
    captured_lat?: number | null;
    captured_lng?: number | null;
    notes?: string | null;
    payload: Record<string, unknown>;
    photo_url?: string | null;
    submission_type: SubmissionType;
}
export interface SubmissionOut {
    captured_at?: string | null;
    captured_lat?: number | null;
    captured_lng?: number | null;
    id: string;
    notes?: string | null;
    payload: Record<string, unknown>;
    photo_url?: string | null;
    status: SubmissionStatus;
    submission_type: SubmissionType;
    submitted_at: string;
    submitted_by?: string | null;
}
export const SubmissionStatus = {
    pending: "pending",
    approved: "approved",
    rejected: "rejected",
    merged: "merged"
} as const;
export type SubmissionStatus = typeof SubmissionStatus[keyof typeof SubmissionStatus];
export const SubmissionType = {
    provider_self_attest: "provider_self_attest",
    fieldwork_surveyor: "fieldwork_surveyor"
} as const;
export type SubmissionType = typeof SubmissionType[keyof typeof SubmissionType];
export interface User {
    active?: boolean | null;
    display_name?: string | null;
    emails?: ComplexValue[] | null;
    entitlements?: ComplexValue[] | null;
    external_id?: string | null;
    groups?: ComplexValue[] | null;
    id?: string | null;
    name?: Name | null;
    roles?: ComplexValue[] | null;
    schemas?: UserSchema[] | null;
    user_name?: string | null;
}
export const UserSchema = {
    "urn:ietf:params:scim:schemas:core:2.0:User": "urn:ietf:params:scim:schemas:core:2.0:User",
    "urn:ietf:params:scim:schemas:extension:workspace:2.0:User": "urn:ietf:params:scim:schemas:extension:workspace:2.0:User"
} as const;
export type UserSchema = typeof UserSchema[keyof typeof UserSchema];
export interface ValidationError {
    ctx?: Record<string, unknown>;
    input?: unknown;
    loc: (string | number)[];
    msg: string;
    type: string;
}
export interface VersionOut {
    version: string;
}
export interface CurrentUserParams {
    "X-Forwarded-Host"?: string | null;
    "X-Forwarded-Preferred-Username"?: string | null;
    "X-Forwarded-User"?: string | null;
    "X-Forwarded-Email"?: string | null;
    "X-Request-Id"?: string | null;
    "X-Forwarded-Access-Token"?: string | null;
}
export const currentUser = async (params?: CurrentUserParams, options?: RequestInit): Promise<{
    data: User;
}> =>{
    const res = await fetch("/api/current-user", {
        ...options,
        method: "GET",
        headers: {
            ...(params?.["X-Forwarded-Host"] != null && {
                "X-Forwarded-Host": params["X-Forwarded-Host"]
            }),
            ...(params?.["X-Forwarded-Preferred-Username"] != null && {
                "X-Forwarded-Preferred-Username": params["X-Forwarded-Preferred-Username"]
            }),
            ...(params?.["X-Forwarded-User"] != null && {
                "X-Forwarded-User": params["X-Forwarded-User"]
            }),
            ...(params?.["X-Forwarded-Email"] != null && {
                "X-Forwarded-Email": params["X-Forwarded-Email"]
            }),
            ...(params?.["X-Request-Id"] != null && {
                "X-Request-Id": params["X-Request-Id"]
            }),
            ...(params?.["X-Forwarded-Access-Token"] != null && {
                "X-Forwarded-Access-Token": params["X-Forwarded-Access-Token"]
            }),
            ...options?.headers
        }
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const currentUserKey = (params?: CurrentUserParams)=>{
    return [
        "/api/current-user",
        params
    ] as const;
};
export function useCurrentUser<TData = {
    data: User;
}>(options?: {
    params?: CurrentUserParams;
    query?: Omit<UseQueryOptions<{
        data: User;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: currentUserKey(options?.params),
        queryFn: ()=>currentUser(options?.params),
        ...options?.query
    });
}
export function useCurrentUserSuspense<TData = {
    data: User;
}>(options?: {
    params?: CurrentUserParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: User;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: currentUserKey(options?.params),
        queryFn: ()=>currentUser(options?.params),
        ...options?.query
    });
}
export const listSpecialties = async (options?: RequestInit): Promise<{
    data: string[];
}> =>{
    const res = await fetch("/api/facilities/specialties", {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const listSpecialtiesKey = ()=>{
    return [
        "/api/facilities/specialties"
    ] as const;
};
export function useListSpecialties<TData = {
    data: string[];
}>(options?: {
    query?: Omit<UseQueryOptions<{
        data: string[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: listSpecialtiesKey(),
        queryFn: ()=>listSpecialties(),
        ...options?.query
    });
}
export function useListSpecialtiesSuspense<TData = {
    data: string[];
}>(options?: {
    query?: Omit<UseSuspenseQueryOptions<{
        data: string[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: listSpecialtiesKey(),
        queryFn: ()=>listSpecialties(),
        ...options?.query
    });
}
export interface GetFacilityParams {
    facility_id: string;
}
export const getFacility = async (params: GetFacilityParams, options?: RequestInit): Promise<{
    data: FacilityOut;
}> =>{
    const res = await fetch(`/api/facilities/${params.facility_id}`, {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const getFacilityKey = (params?: GetFacilityParams)=>{
    return [
        "/api/facilities/{facility_id}",
        params
    ] as const;
};
export function useGetFacility<TData = {
    data: FacilityOut;
}>(options: {
    params: GetFacilityParams;
    query?: Omit<UseQueryOptions<{
        data: FacilityOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: getFacilityKey(options.params),
        queryFn: ()=>getFacility(options.params),
        ...options?.query
    });
}
export function useGetFacilitySuspense<TData = {
    data: FacilityOut;
}>(options: {
    params: GetFacilityParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: FacilityOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: getFacilityKey(options.params),
        queryFn: ()=>getFacility(options.params),
        ...options?.query
    });
}
export const search = async (data: SearchIn, options?: RequestInit): Promise<{
    data: SearchResults;
}> =>{
    const res = await fetch("/api/search", {
        ...options,
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...options?.headers
        },
        body: JSON.stringify(data)
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export function useSearch(options?: {
    mutation?: UseMutationOptions<{
        data: SearchResults;
    }, ApiError, SearchIn>;
}) {
    return useMutation({
        mutationFn: (data)=>search(data),
        ...options?.mutation
    });
}
export interface CreateSubmissionParams {
    "X-Forwarded-Host"?: string | null;
    "X-Forwarded-Preferred-Username"?: string | null;
    "X-Forwarded-User"?: string | null;
    "X-Forwarded-Email"?: string | null;
    "X-Request-Id"?: string | null;
    "X-Forwarded-Access-Token"?: string | null;
}
export const createSubmission = async (data: SubmissionIn, params?: CreateSubmissionParams, options?: RequestInit): Promise<{
    data: SubmissionOut;
}> =>{
    const res = await fetch("/api/submissions", {
        ...options,
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...(params?.["X-Forwarded-Host"] != null && {
                "X-Forwarded-Host": params["X-Forwarded-Host"]
            }),
            ...(params?.["X-Forwarded-Preferred-Username"] != null && {
                "X-Forwarded-Preferred-Username": params["X-Forwarded-Preferred-Username"]
            }),
            ...(params?.["X-Forwarded-User"] != null && {
                "X-Forwarded-User": params["X-Forwarded-User"]
            }),
            ...(params?.["X-Forwarded-Email"] != null && {
                "X-Forwarded-Email": params["X-Forwarded-Email"]
            }),
            ...(params?.["X-Request-Id"] != null && {
                "X-Request-Id": params["X-Request-Id"]
            }),
            ...(params?.["X-Forwarded-Access-Token"] != null && {
                "X-Forwarded-Access-Token": params["X-Forwarded-Access-Token"]
            }),
            ...options?.headers
        },
        body: JSON.stringify(data)
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export function useCreateSubmission(options?: {
    mutation?: UseMutationOptions<{
        data: SubmissionOut;
    }, ApiError, {
        params: CreateSubmissionParams;
        data: SubmissionIn;
    }>;
}) {
    return useMutation({
        mutationFn: (vars)=>createSubmission(vars.data, vars.params),
        ...options?.mutation
    });
}
export interface ListMySubmissionsParams {
    limit?: number;
    "X-Forwarded-Host"?: string | null;
    "X-Forwarded-Preferred-Username"?: string | null;
    "X-Forwarded-User"?: string | null;
    "X-Forwarded-Email"?: string | null;
    "X-Request-Id"?: string | null;
    "X-Forwarded-Access-Token"?: string | null;
}
export const listMySubmissions = async (params?: ListMySubmissionsParams, options?: RequestInit): Promise<{
    data: SubmissionOut[];
}> =>{
    const searchParams = new URLSearchParams();
    if (params?.limit != null) searchParams.set("limit", String(params?.limit));
    const queryString = searchParams.toString();
    const url = queryString ? `/api/submissions/mine?${queryString}` : "/api/submissions/mine";
    const res = await fetch(url, {
        ...options,
        method: "GET",
        headers: {
            ...(params?.["X-Forwarded-Host"] != null && {
                "X-Forwarded-Host": params["X-Forwarded-Host"]
            }),
            ...(params?.["X-Forwarded-Preferred-Username"] != null && {
                "X-Forwarded-Preferred-Username": params["X-Forwarded-Preferred-Username"]
            }),
            ...(params?.["X-Forwarded-User"] != null && {
                "X-Forwarded-User": params["X-Forwarded-User"]
            }),
            ...(params?.["X-Forwarded-Email"] != null && {
                "X-Forwarded-Email": params["X-Forwarded-Email"]
            }),
            ...(params?.["X-Request-Id"] != null && {
                "X-Request-Id": params["X-Request-Id"]
            }),
            ...(params?.["X-Forwarded-Access-Token"] != null && {
                "X-Forwarded-Access-Token": params["X-Forwarded-Access-Token"]
            }),
            ...options?.headers
        }
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const listMySubmissionsKey = (params?: ListMySubmissionsParams)=>{
    return [
        "/api/submissions/mine",
        params
    ] as const;
};
export function useListMySubmissions<TData = {
    data: SubmissionOut[];
}>(options?: {
    params?: ListMySubmissionsParams;
    query?: Omit<UseQueryOptions<{
        data: SubmissionOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: listMySubmissionsKey(options?.params),
        queryFn: ()=>listMySubmissions(options?.params),
        ...options?.query
    });
}
export function useListMySubmissionsSuspense<TData = {
    data: SubmissionOut[];
}>(options?: {
    params?: ListMySubmissionsParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: SubmissionOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: listMySubmissionsKey(options?.params),
        queryFn: ()=>listMySubmissions(options?.params),
        ...options?.query
    });
}
export const version = async (options?: RequestInit): Promise<{
    data: VersionOut;
}> =>{
    const res = await fetch("/api/version", {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const versionKey = ()=>{
    return [
        "/api/version"
    ] as const;
};
export function useVersion<TData = {
    data: VersionOut;
}>(options?: {
    query?: Omit<UseQueryOptions<{
        data: VersionOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: versionKey(),
        queryFn: ()=>version(),
        ...options?.query
    });
}
export function useVersionSuspense<TData = {
    data: VersionOut;
}>(options?: {
    query?: Omit<UseSuspenseQueryOptions<{
        data: VersionOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: versionKey(),
        queryFn: ()=>version(),
        ...options?.query
    });
}
