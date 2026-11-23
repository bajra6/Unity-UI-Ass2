using System.Collections;
using UnityEngine;

// Procedural actions share the existing rig and preserve its mouth attachment.
public class DogExtraActions : MonoBehaviour
{
    Transform actor, body;
    DogMeshRig rig;
    Quaternion heading;
    GameObject streamObject;
    Material streamMaterial;

    public IEnumerator Perform(string action, Transform dog, Transform visual, DogMeshRig dogRig)
    {
        ResetPose();
        actor = dog; body = visual; rig = dogRig; heading = dog.rotation;
        if (action == "pee")
        {
            // Face sideways to the approached destination, presenting the right hind leg.
            float duration = 5.6f;
            for (float time = 0; time < duration; time += Time.deltaTime)
            {
                float turn = Mathf.SmoothStep(0, 1, Mathf.Clamp01(time / .65f));
                actor.rotation = heading * Quaternion.Euler(0, -90 * turn, 0);
                float lift = Mathf.SmoothStep(0, 1, Mathf.Clamp01((time - .5f) / .8f))
                    * (1 - Mathf.SmoothStep(0, 1, Mathf.Clamp01((time - 4.6f) / .75f)));
                rig.SetSpecialPose(lift, 0);
                body.localPosition = new Vector3(-.025f * lift, -.015f * lift, 0);
                if (time > 1.35f && time < 4.6f) DrawStream(time, Mathf.Min(1, (time - 1.35f) * 5, (4.6f - time) * 5));
                else if (streamObject) streamObject.SetActive(false);
                yield return null;
            }
        }
        else
        {
            for (float time = 0; time < 2.8f; time += Time.deltaTime)
            {
                float dip = Mathf.SmoothStep(0, 1, Mathf.Clamp01(time / .5f))
                    * (1 - Mathf.SmoothStep(0, 1, Mathf.Clamp01((time - 2.2f) / .6f)));
                rig.SetSpecialPose(0, dip);
                body.localRotation = Quaternion.Euler(14 * dip, Mathf.Sin(time * 5) * 7 * dip, 0);
                body.localPosition = new Vector3(0, -.07f * dip + Mathf.Sin(time * 17) * .006f * dip, 0);
                yield return null;
            }
        }
        ResetPose();
    }

    void DrawStream(float time, float strength)
    {
        if (!streamObject)
        {
            streamObject = new GameObject("Pee stream");
            streamObject.transform.SetParent(transform, false);
            var line = streamObject.AddComponent<LineRenderer>();
            var shader = Shader.Find("Universal Render Pipeline/Unlit");
            if (!shader) shader = Shader.Find("Sprites/Default");
            streamMaterial = new Material(shader) { color = new Color(.80f, .73f, .28f) };
            line.sharedMaterial = streamMaterial;
            line.positionCount = 24;
            line.useWorldSpace = true;
            line.numCapVertices = 3;
            line.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            line.receiveShadows = false;
        }
        streamObject.SetActive(true);
        var stream = streamObject.GetComponent<LineRenderer>();
        stream.startWidth = .012f * strength;
        stream.endWidth = .004f * strength;
        Vector3 origin = actor.TransformPoint(new Vector3(.14f, .34f, -.25f));
        Vector3 velocity = actor.right * (2.65f + Mathf.Sin(time * 13) * .05f) + Vector3.up * .18f;
        for (int i = 0; i < stream.positionCount; i++)
        {
            float t = i / (float)(stream.positionCount - 1) * .48f;
            Vector3 point = origin + velocity * t + Vector3.down * (2 * t * t);
            point.y = Mathf.Max(.015f, point.y);
            stream.SetPosition(i, point);
        }
    }

    public void ResetPose()
    {
        if (actor) actor.rotation = heading;
        if (body) { body.localPosition = Vector3.zero; body.localRotation = Quaternion.identity; }
        if (rig) rig.SetSpecialPose(0, 0);
        if (streamObject) { streamObject.SetActive(false); Destroy(streamObject); }
        if (streamMaterial) Destroy(streamMaterial);
        streamObject = null; streamMaterial = null; actor = null; body = null; rig = null;
    }

    void OnDisable() { ResetPose(); }
}
