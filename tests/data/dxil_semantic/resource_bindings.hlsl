cbuffer Params : register(b2, space1) { float scale; };
Texture2D<float4> inputs[2] : register(t3, space2);
SamplerState linear_sampler : register(s1, space4);
RWStructuredBuffer<float4> outputs : register(u5, space3);

[numthreads(1, 1, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    float2 uv = float2(id.xy) * scale;
    outputs[id.x] = inputs[NonUniformResourceIndex(id.x & 1)].SampleLevel(linear_sampler, uv, 0);
}
