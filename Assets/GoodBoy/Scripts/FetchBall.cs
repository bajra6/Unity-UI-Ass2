using UnityEngine;

// Physics owns the ball in flight; the mouth owns it while carrying.
// Once it contacts the floor it becomes stationary until the next throw/pickup.
public class FetchBall : MonoBehaviour
{
    public const float Radius = .26f;
    Rigidbody body;
    Transform socket;
    public bool IsCarried => socket != null;
    public bool IsSettled => !socket && body.isKinematic;

    void Awake() { body = GetComponent<Rigidbody>(); }

    public void Carry(Transform mouth)
    {
        if (!body.isKinematic) { body.linearVelocity = Vector3.zero; body.angularVelocity = Vector3.zero; }
        body.interpolation = RigidbodyInterpolation.None;
        body.collisionDetectionMode = CollisionDetectionMode.Discrete;
        body.isKinematic = true;
        body.detectCollisions = false;
        socket = mouth;
        transform.SetParent(mouth, true);
        FollowMouth();
    }

    void LateUpdate() { if (socket) FollowMouth(); }

    void FollowMouth()
    {
        // Update both poses: interpolation must never restore a stale world-space pose.
        transform.SetLocalPositionAndRotation(Vector3.zero, Quaternion.identity);
        body.position = socket.position;
        body.rotation = socket.rotation;
    }

    public void Launch(Transform world, Vector3 position, Vector3 velocity)
    {
        socket = null;
        transform.SetParent(world, true);
        body.interpolation = RigidbodyInterpolation.None;
        body.position = position;
        transform.position = position;
        body.rotation = Quaternion.identity;
        body.detectCollisions = true;
        body.isKinematic = false;
        body.constraints = RigidbodyConstraints.FreezeRotation;
        body.collisionDetectionMode = CollisionDetectionMode.ContinuousDynamic;
        body.linearVelocity = velocity;
        body.angularVelocity = Vector3.zero;
    }

    public void Place(Transform world, Vector3 position)
    {
        Launch(world, position, Vector3.zero);
        Settle();
    }

    void OnCollisionEnter(Collision collision) { CheckFloor(collision); }
    void OnCollisionStay(Collision collision) { CheckFloor(collision); }
    void CheckFloor(Collision collision)
    {
        if (socket || body.isKinematic) return;
        foreach (var contact in collision.contacts)
            if (contact.normal.y > .7f) { Settle(); break; }
    }

    void Settle()
    {
        body.linearVelocity = Vector3.zero;
        body.angularVelocity = Vector3.zero;
        body.collisionDetectionMode = CollisionDetectionMode.Discrete;
        body.isKinematic = true;
    }
}
