using UnityEngine;

// Lightweight spatial skinning for the CC0 standing dog. Keeps the continuous
// anatomical mesh, with four leg joints and a tail instead of separate cubes.
public class DogMeshRig : MonoBehaviour
{
    readonly Transform[] joints = new Transform[6];
    readonly Vector3[] pivots = {
        Vector3.zero, new Vector3(-.13f,.47f,.32f), new Vector3(.13f,.47f,.32f),
        new Vector3(-.13f,.48f,-.36f), new Vector3(.13f,.48f,-.36f), new Vector3(0,.57f,-.48f)
    };
    float stride, sitting;
    float marking, sniffing;
    public void SetSpecialPose(float pee, float sniff) { marking = pee; sniffing = sniff; }
    public void SetPose(float walking, bool seated) { stride = walking; sitting = seated ? 1 : 0; }
    public void SetSeated(bool seated) { sitting = seated ? 1 : 0; }

    void Awake()
    {
        for (int i=0;i<joints.Length;i++)
        {
            joints[i] = new GameObject(i == 0 ? "Body joint" : i == 5 ? "Tail joint" : "Leg joint " + i).transform;
            joints[i].SetParent(transform,false);
            joints[i].localPosition = pivots[i];
        }
        foreach (var filter in GetComponentsInChildren<MeshFilter>())
        {
            var old = filter.GetComponent<MeshRenderer>();
            if (!old) continue;
            var mesh = Instantiate(filter.sharedMesh);
            var vertices=mesh.vertices;
            bool rigidFoot = filter.name.StartsWith("Toe") || filter.name.StartsWith("Rounded paw");
            Vector3 footCenter = transform.InverseTransformPoint(filter.transform.TransformPoint(mesh.bounds.center));
            int footJoint = (footCenter.z > 0 ? 1 : 3) + (footCenter.x > 0 ? 1 : 0);
            var weights=new BoneWeight[vertices.Length];
            var bind=new Matrix4x4[joints.Length];
            for(int i=0;i<joints.Length;i++) bind[i]=joints[i].worldToLocalMatrix*filter.transform.localToWorldMatrix;
            for(int i=0;i<vertices.Length;i++)
            {
                Vector3 p=transform.InverseTransformPoint(filter.transform.TransformPoint(vertices[i]));
                int joint=0; float weight=0;
                if(p.y<.54f)
                {
                    joint=(p.z>0 ? 1:3)+(p.x>0 ? 1:0);
                    // Keep the entire lower leg moving. Blend smoothly into the belly,
                    // instead of leaving a hard strip of inner-paw vertices on the body.
                    float heightWeight=1-Mathf.SmoothStep(0,1,Mathf.InverseLerp(.28f,.54f,p.y));
                    float sideWeight=Mathf.SmoothStep(0,1,Mathf.InverseLerp(.02f,.09f,Mathf.Abs(p.x)));
                    float hipBlend=Mathf.SmoothStep(0,1,Mathf.InverseLerp(.28f,.45f,p.y));
                    weight=heightWeight*Mathf.Lerp(1,sideWeight,hipBlend);
                }
                if(p.z<-.49f && p.y>.43f)
                {
                    joint=5; weight=Mathf.SmoothStep(0,1,Mathf.InverseLerp(-.49f,-.73f,p.z));
                }
                // Paw/toe objects must remain rigid: splitting one across the body and
                // hip bones stretched its triangles all the way back to the ground.
                weights[i]=rigidFoot ? new BoneWeight { boneIndex0=footJoint,weight0=1 }
                    : new BoneWeight { boneIndex0=0,weight0=1-weight,boneIndex1=joint,weight1=weight };
            }
            mesh.boneWeights=weights; mesh.bindposes=bind;
            // Unity permits only one renderer on a GameObject. Use a child rather
            // than replacing MeshRenderer before its materials have been copied.
            var skinObject=new GameObject("Animated mesh");
            skinObject.transform.SetParent(filter.transform,false);
            var skin=skinObject.AddComponent<SkinnedMeshRenderer>();
            skin.sharedMesh=mesh; skin.sharedMaterials=old.sharedMaterials;
            for(int j=0;j<old.sharedMaterials.Length;j++)
            {
                var properties=new MaterialPropertyBlock();old.GetPropertyBlock(properties,j);skin.SetPropertyBlock(properties,j);
            }
            skin.bones=joints; skin.rootBone=joints[0]; skin.updateWhenOffscreen=true;
            skin.localBounds=new Bounds(mesh.bounds.center,mesh.bounds.size+Vector3.one*2);
            old.enabled=false;
            Destroy(old); Destroy(filter);
        }
    }

    void LateUpdate()
    {
        joints[0].localPosition = new Vector3(-.025f * marking, 0, 0);
        joints[0].localRotation = Quaternion.Euler(12 * sniffing, 0, -4 * marking);
        for(int i=1;i<=4;i++)
        {
            float phase=Time.time*10+(i==1 || i==4 ? 0:Mathf.PI);
            joints[i].localRotation=Quaternion.Euler(Mathf.Sin(phase)*25*stride+(i>=3 ? -65*sitting:0),0,0);
        }
        // Shift onto three supporting legs, then abduct the right rear leg at its hip.
        joints[4].localRotation *= Quaternion.Euler(-18 * marking, 0, 72 * marking);
        joints[3].localRotation *= Quaternion.Euler(0, 0, -6 * marking);
        joints[5].localRotation=Quaternion.Euler(-12 * marking,Mathf.Sin(Time.time*6)*Mathf.Lerp(22, 5, marking),0);
        stride=Mathf.MoveTowards(stride,0,Time.deltaTime*7);
    }
}
